"""CLI parsing and server launch orchestration."""

import argparse
import atexit
import os
import platform
import random
import re
import signal
import sys
import threading
import time
from pathlib import Path

from .browser import launch_browser_window
from .config import Config
from .constants import (
    CLEAR,
    CLR_B,
    CLR_BLD,
    CLR_C,
    CLR_G,
    CLR_M,
    CLR_RST,
    CLR_Y,
    ERR,
    INFO,
    OK,
    WRN,
    __version__,
)
from .history import print_history
from .hotspot import HotspotHelper
from .keyboard import read_key
from .qr import generate_qr_code, generate_qr_svg
from .server import FileTransferHandler, ThreadingHTTPServer
from .sync import sender_sync
from .tui import run_tui
from .tunnels import TunnelManager
from .utils import find_available_port, format_size, get_lan_ip


# ─────────────────────────────────────────────────────────
#  POST-TUI LAUNCH  (server + QR)
# ─────────────────────────────────────────────────────────
def launch_server(
    is_send,
    file_paths,
    mode_name,
    port,
    no_qr=False,
    expire_seconds=None,
    no_browser=False,
    existing_server=None,
):
    """Everything that happens after the user confirms in the TUI or starts CLI."""
    Config.LOCAL_PORT = port
    if not Config.OTP:
        Config.OTP = f"{random.randint(0, 9999):04d}"

    # map mode_name → flags
    lan_only = mode_name == "LAN"
    if mode_name == "SSH":
        noauth_mode = True
    elif mode_name == "Ngrok":
        noauth_mode = False
    elif mode_name == "Cloudflare":
        noauth_mode = True
    else:  # LAN
        noauth_mode = True
    tunnel_backend = mode_name.lower() if mode_name in ("Cloudflare", "Ngrok") else None

    # ── banner ──
    print("\n" + "=" * 60)
    print("qrtunnel - Simple File Transfer")
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Port:     {Config.LOCAL_PORT}")
    print(f"Security: LAN Access Code -> [{CLR_G}{Config.OTP}{CLR_RST}] (valid for this session)")
    print(f"Mode:     {'Send (share)' if is_send else 'Receive (upload)'}")
    print(f"Tunnel:   {mode_name}")
    print("=" * 60)

    if is_send:
        print("Files to be shared:")
        for fp in file_paths:
            print(f"  - {os.path.basename(fp)} ({format_size(os.path.getsize(fp))})")
        print("=" * 60)
    else:
        print(f"Upload directory:\n  - {os.getcwd()}")
        print("=" * 60)

    # ── LAN / Hotspot check ──
    current_lan_ip = get_lan_ip()
    if not current_lan_ip and not lan_only:
        hotspot_helper = HotspotHelper()
        qr_data = hotspot_helper.get_qr_data()
        if qr_data:
            qr_string, ssid, password = qr_data
            print(f"\n{INFO} 📡 Faster local transfer available")
            print("Turn on your phone hotspot and scan this QR to connect automatically:")
            print("=" * 60)
            try:
                import qrcode

                qr = qrcode.QRCode()
                qr.add_data(qr_string)
                qr.make(fit=True)
                qr.print_ascii(invert=True)
            except ImportError:
                print(f"{WRN} qrcode library not installed.")
            print("=" * 60)
            print(f"SSID:     {ssid}")
            print(f"Password: {password}")
            print("=" * 60)
            print(f"{INFO} Waiting for connection…")
            try:
                for _ in range(15):
                    time.sleep(2)
                    new_ip = get_lan_ip()
                    if new_ip:
                        print(f"\n{OK} LAN Connection Detected: {new_ip}")
                        current_lan_ip = new_ip
                        break
            except KeyboardInterrupt:
                print("\nSkipping LAN wait…")

    # ── tunnel manager ──
    tunnel_manager = TunnelManager(
        Config.LOCAL_PORT,
        noauth=noauth_mode,
        lan_only=lan_only,
        lan_ip=current_lan_ip,
        tunnel_backend=tunnel_backend,
    )

    # ── HTTP handler setup ──
    FileTransferHandler.file_paths = file_paths if is_send else None
    FileTransferHandler.upload_mode = not is_send
    FileTransferHandler.server_lan_ip = current_lan_ip

    # ── start HTTP server if not reusing existing ──
    if existing_server is not None:
        server = existing_server
    else:
        try:
            server = ThreadingHTTPServer(("0.0.0.0", Config.LOCAL_PORT), FileTransferHandler)
        except OSError as e:
            print(f"\n{ERR} Error: Could not bind to port {Config.LOCAL_PORT}\n   {e}")
            sys.exit(1)

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        print(f"\n{OK} HTTP server started on all interfaces (port {Config.LOCAL_PORT})")

        sender_sync.initialize(port=Config.LOCAL_PORT, pin=Config.OTP, lan_ip=current_lan_ip)
        sender_sync.server = server

    stopped = False

    def cleanup():
        nonlocal stopped
        if stopped:
            return
        stopped = True
        sender_sync.close_from_terminal()
        tunnel_manager.stop()
        server.shutdown()
        server.server_close()

    atexit.register(cleanup)
    previous_sigint = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum, frame):
        print("\n[*] Ctrl+C pressed. Shutting down…")
        cleanup()
        sys.exit(130)

    try:
        signal.signal(signal.SIGINT, handle_sigint)
    except ValueError:
        previous_sigint = None

    # ── start tunnel ──
    if not tunnel_manager.start():
        cleanup()
        sys.exit(1)

    # ── QR code and sync ──
    target_url = (
        tunnel_manager.lan_url
        if lan_only
        else (tunnel_manager.public_url or tunnel_manager.lan_url)
    )
    qr_svg = generate_qr_svg(target_url)

    sender_sync.set_active_transfer(
        is_send=is_send,
        file_paths=file_paths,
        mode_name=mode_name,
        port=Config.LOCAL_PORT,
        target_url=target_url,
        pin=Config.OTP,
        qr_svg=qr_svg,
    )

    if not no_browser and not sender_sync.browser_connected:
        launch_browser_window(f"http://127.0.0.1:{Config.LOCAL_PORT}/sender")

    generate_qr_code(target_url, no_qr=no_qr)

    if expire_seconds:
        print(f"[*] Server is running for {expire_seconds} seconds. Press 'q' or Ctrl+C to stop.\n")
        shutdown_at = time.monotonic() + expire_seconds
    else:
        print("[*] Server is running.  Press 'q' or Ctrl+C to stop.\n")
        shutdown_at = None

    # ── wait loop ──
    try:
        while True:
            if sender_sync.is_closed():
                print("\n[*] Browser closed or session ended. Shutting down…")
                break
            if shutdown_at and time.monotonic() >= shutdown_at:
                print("\n[*] Expiration reached. Shutting down…")
                break
            key = read_key()
            if sender_sync.is_closed():
                print("\n[*] Browser closed or session ended. Shutting down…")
                break
            if key and key.lower() == "q":
                print("\n[*] 'q' pressed. Shutting down…")
                break
            if key == "CTRL_C":
                print("\n[*] Ctrl+C pressed. Shutting down…")
                break
    except KeyboardInterrupt:
        print("\n[*] Ctrl+C pressed. Shutting down…")
    finally:
        cleanup()
        atexit.unregister(cleanup)
        if previous_sigint is not None:
            signal.signal(signal.SIGINT, previous_sigint)
        print("[*] Server stopped. Goodbye!")


# ─────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────
def parse_args():
    """Parse command line arguments, handling the custom port syntax."""
    # 1. Custom Port Pre-processing (e.g., -8080 or --6969)
    argv = sys.argv[1:]
    port = 6969  # Default port
    clean_argv = []

    for arg in argv:
        # Match -1234 or --1234
        if re.match(r"^--?\d{2,5}$", arg):
            try:
                p = int(arg.lstrip("-"))
                if 1 <= p <= 65535:
                    port = p
                    continue
            except ValueError:
                pass
        clean_argv.append(arg)

    # 2. Argparse Setup
    parser = argparse.ArgumentParser(
        description="qrtunnel: Elegant cross-platform file sharing via QR code.",
        usage="%(prog)s [send|receive|tui|history] [files/dir] [options] [-PORT]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  qrtunnel                        # Start Sender Web UI in new browser window (default)
  qrtunnel tui                    # Start interactive TUI in terminal
  qrtunnel send photo.jpg         # Share a file on local Wi-Fi (LAN)
  qrtunnel send docs/ -cloudflare # Share directory via Cloudflare tunnel
  qrtunnel receive ./uploads      # Receive files into a specific folder
  qrtunnel receive -ngrok         # Receive files via ngrok tunnel
""",
    )

    # Global options for top-level (running 'qrtunnel' directly in UI mode)
    parser.add_argument("--port", "-p", type=int, help="Specify port manually (e.g. -p 8080)")
    parser.add_argument(
        "--no-qr",
        action="store_true",
        help="Suppress terminal QR output and print only access links",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Suppress automatic browser window opening",
    )
    parser.add_argument("--expire", type=int, help="Auto-shutdown after N seconds")
    parser.add_argument("-v", "--version", action="version", version=f"qrtunnel {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # TUI command
    p_tui = subparsers.add_parser("tui", help="Start interactive terminal TUI")

    # SEND command
    p_send = subparsers.add_parser("send", help="Share files or directories with others")
    p_send.add_argument("files", nargs="+", help="Path to files or folders to share")

    # RECEIVE command
    p_recv = subparsers.add_parser("receive", help="Receive files from others")
    p_recv.add_argument(
        "dest", nargs="?", default=".", help="Directory to save received files (default: current)"
    )

    # HISTORY command
    p_history = subparsers.add_parser("history", help="Show recent transfer history")
    p_history.add_argument("--limit", type=int, default=20, help="Number of entries to show")

    # Options for subcommands
    for p in [p_send, p_recv, p_tui]:
        g = p.add_argument_group("Tunneling Options")
        m = g.add_mutually_exclusive_group()
        m.add_argument(
            "-lan", action="store_true", help="LAN Only: Fast local transfer (same Wi-Fi) [default]"
        )
        m.add_argument(
            "-ssh", action="store_true", help="SSH Tunnel: No-auth public link (localhost.run)"
        )
        m.add_argument(
            "-ngrok",
            action="store_true",
            help="Ngrok Tunnel: Secure public link (requires account)",
        )
        m.add_argument(
            "-cloudflare",
            action="store_true",
            help="Cloudflare Tunnel: Public link via cloudflared",
        )

        p.add_argument("--port", "-p", type=int, help="Specify port manually (e.g. -p 8080)")
        p.add_argument(
            "--no-qr",
            action="store_true",
            help="Suppress terminal QR output and print only access links",
        )
        p.add_argument(
            "--no-browser",
            action="store_true",
            help="Suppress automatic browser window opening",
        )
        p.add_argument("--expire", type=int, help="Auto-shutdown after N seconds")
        p.add_argument("-v", "--version", action="version", version=f"qrtunnel {__version__}")

    args = parser.parse_args(clean_argv)

    # Override port if explicitly set via --port or custom port syntax
    if getattr(args, "port", None):
        port = args.port

    if getattr(args, "expire", None) is not None and args.expire <= 0:
        parser.error("--expire must be greater than 0")

    return args, port


def validate_receive_destination(dest):
    target_dir = Path(dest).expanduser().resolve()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"{ERR} Could not create destination directory: {target_dir}\n   {e}")
        sys.exit(1)

    if not target_dir.is_dir():
        print(f"{ERR} Destination is not a directory: {target_dir}")
        sys.exit(1)
    if not os.access(target_dir, os.W_OK):
        print(f"{ERR} Destination is not writable: {target_dir}")
        sys.exit(1)
    return str(target_dir)


def validate_send_paths(paths):
    file_paths = []
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            print(f"{ERR} File not found: {resolved}")
            sys.exit(1)
        file_paths.append(str(resolved))
    return file_paths


def main():
    args, cli_port = parse_args()
    no_browser = getattr(args, "no_browser", False) or ("--no-browser" in sys.argv)
    expire_seconds = getattr(args, "expire", None)
    no_qr = getattr(args, "no_qr", False)

    # ── DEFAULT / SENDER WEB UI MODE (no command specified) ──
    if args.command is None:
        port = cli_port if cli_port else find_available_port()
        Config.LOCAL_PORT = port
        Config.OTP = f"{random.randint(0, 9999):04d}"
        current_lan_ip = get_lan_ip()
        FileTransferHandler.server_lan_ip = current_lan_ip
        FileTransferHandler.file_paths = None
        FileTransferHandler.upload_mode = False

        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), FileTransferHandler)
        except OSError as e:
            print(f"\n{ERR} Error: Could not bind to port {port}\n   {e}")
            sys.exit(1)

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        sender_sync.initialize(port=port, pin=Config.OTP, lan_ip=current_lan_ip)
        sender_sync.server = server

        if not no_browser:
            launch_browser_window(f"http://127.0.0.1:{port}/sender")

        sender_url = f"http://127.0.0.1:{port}/sender"
        print("\n" + "=" * 60)
        print(f"  {CLR_B}{CLR_BLD}qrtunnel{CLR_RST}")
        print("=" * 60)
        print(f"  Sender Web UI : {CLR_C}{sender_url}{CLR_RST}")
        print(f"  Access Code   : {CLR_Y}{Config.OTP}{CLR_RST}")
        print(f"  Status        : {CLR_G}Opened in a new browser window{CLR_RST}")
        print("=" * 60)
        if expire_seconds:
            print(
                f"[*] Server is running for {expire_seconds} seconds. Press 'q' or Ctrl+C to stop.\n"
            )
            shutdown_at = time.monotonic() + expire_seconds
        else:
            print("[*] Server is running. Press 'q' or Ctrl+C in terminal or Stop in browser.\n")
            shutdown_at = None

        stopped = False

        def cleanup():
            nonlocal stopped
            if stopped:
                return
            stopped = True
            sender_sync.close_from_terminal()
            if sender_sync.tunnel_manager:
                sender_sync.tunnel_manager.stop()
            server.shutdown()
            server.server_close()

        atexit.register(cleanup)
        previous_sigint = signal.getsignal(signal.SIGINT)

        def handle_sigint(signum, frame):
            print("\n[*] Ctrl+C pressed. Shutting down…")
            cleanup()
            sys.exit(130)

        try:
            signal.signal(signal.SIGINT, handle_sigint)
        except ValueError:
            previous_sigint = None

        try:
            while True:
                if sender_sync.is_closed():
                    print("\n[*] Browser closed or session ended. Shutting down…")
                    break
                if shutdown_at and time.monotonic() >= shutdown_at:
                    print("\n[*] Expiration reached. Shutting down…")
                    break
                key = read_key()
                if sender_sync.is_closed():
                    print("\n[*] Browser closed or session ended. Shutting down…")
                    break
                if key and key.lower() == "q":
                    print("\n[*] 'q' pressed. Shutting down…")
                    break
                if key == "CTRL_C":
                    print("\n[*] Ctrl+C pressed. Shutting down…")
                    break
        except KeyboardInterrupt:
            print("\n[*] Ctrl+C pressed. Shutting down…")
        finally:
            cleanup()
            atexit.unregister(cleanup)
            if previous_sigint is not None:
                signal.signal(signal.SIGINT, previous_sigint)
            print("[*] Server stopped. Goodbye!\n")
            sys.exit(0)

    # ── TUI MODE (`qrtunnel tui`) ──
    if args.command == "tui":
        port = cli_port if cli_port else find_available_port()
        Config.LOCAL_PORT = port
        Config.OTP = f"{random.randint(0, 9999):04d}"
        current_lan_ip = get_lan_ip()
        FileTransferHandler.server_lan_ip = current_lan_ip
        FileTransferHandler.file_paths = None
        FileTransferHandler.upload_mode = False

        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), FileTransferHandler)
        except OSError as e:
            print(f"\n{ERR} Error: Could not bind to port {port}\n   {e}")
            sys.exit(1)

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        sender_sync.initialize(port=port, pin=Config.OTP, lan_ip=current_lan_ip)
        sender_sync.server = server

        if not no_browser:
            launch_browser_window(f"http://127.0.0.1:{port}/sender")

        result = run_tui()
        if result is None:
            sender_sync.close_from_terminal()
            server.shutdown()
            server.server_close()
            print("\n[*] Exited. Goodbye!\n")
            sys.exit(0)

        is_send, file_paths, mode_name, chosen_port = result

        if is_send and not file_paths:
            sender_sync.close_from_terminal()
            server.shutdown()
            server.server_close()
            sys.stdout.write(CLEAR)
            print(f"\n{ERR} No files selected. Please re-run and select at least one file.\n")
            sys.exit(1)

        if chosen_port != port and not sender_sync.transfer_started_event.is_set():
            server.shutdown()
            server.server_close()
            server = None

        launch_server(
            is_send,
            file_paths,
            mode_name,
            chosen_port,
            no_qr=no_qr,
            expire_seconds=expire_seconds,
            no_browser=no_browser,
            existing_server=server,
        )
        return

    # ── CLI MODE ──
    if args.command == "history":
        print_history(limit=args.limit)
        return

    is_send = args.command == "send"

    if is_send:
        file_paths = validate_send_paths(args.files)
    else:
        # Receive mode
        target_dir = validate_receive_destination(args.dest)
        os.chdir(target_dir)  # Switch to dest dir for receiving
        file_paths = []

    # Determine Mode (Default to LAN)
    mode_name = "LAN"
    if args.cloudflare:
        mode_name = "Cloudflare"
    elif args.ssh:
        mode_name = "SSH"
    elif args.ngrok:
        mode_name = "Ngrok"
    elif args.lan:
        mode_name = "LAN"

    # Confirmation
    print("\n" + "=" * 60)
    print(f"  {CLR_B}{CLR_BLD}qrtunnel CLI{CLR_RST}")
    print("=" * 60)
    print(
        f"  Direction  : {CLR_G if is_send else CLR_C}{'SEND' if is_send else 'RECEIVE'}{CLR_RST}"
    )
    print(f"  Mode       : {CLR_M}{mode_name}{CLR_RST}")
    print(f"  Port       : {CLR_Y}{cli_port}{CLR_RST}")

    if is_send:
        print(f"  Files ({len(file_paths)}):")
        for f in file_paths[:5]:
            print(f"    - {os.path.basename(f)}")
        if len(file_paths) > 5:
            print(f"    ... and {len(file_paths) - 5} more")
    else:
        print(f"  Save to    : {os.getcwd()}")
    print("=" * 60)

    try:
        ans = input("\nProceed? [Y/n] ").strip().lower()
        if ans not in ("", "y", "yes"):
            print("\n[*] Cancelled.")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n[*] Cancelled.")
        sys.exit(0)

    launch_server(
        is_send,
        file_paths,
        mode_name,
        cli_port,
        no_qr=args.no_qr,
        expire_seconds=args.expire,
        no_browser=no_browser,
    )


if __name__ == "__main__":
    main()
