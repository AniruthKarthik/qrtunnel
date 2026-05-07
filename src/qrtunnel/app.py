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
from .hotspot import HotspotHelper
from .keyboard import read_key
from .qr import generate_qr_code
from .server import FileTransferHandler, ThreadingHTTPServer
from .tui import run_tui
from .tunnels import TunnelManager
from .utils import format_size, get_lan_ip


# ─────────────────────────────────────────────────────────
#  POST-TUI LAUNCH  (server + QR)
# ─────────────────────────────────────────────────────────
def launch_server(is_send, file_paths, mode_name, port, no_qr=False, expire_seconds=None):
    """Everything that happens after the user confirms in the TUI."""
    Config.LOCAL_PORT = port
    Config.OTP = f"{random.randint(0, 999999):06d}"

    # map mode_name → flags
    lan_only = mode_name == "LAN"
    if mode_name == "SSH":
        noauth_mode = True
    elif mode_name == "Ngrok":
        noauth_mode = False
    else:  # Smart, LAN, etc.
        noauth_mode = True

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
        Config.LOCAL_PORT, noauth=noauth_mode, lan_only=lan_only, lan_ip=current_lan_ip
    )

    # ── HTTP handler setup ──
    FileTransferHandler.file_paths = file_paths if is_send else None
    FileTransferHandler.upload_mode = not is_send
    FileTransferHandler.server_lan_ip = current_lan_ip

    # ── start HTTP server ──
    try:
        server = ThreadingHTTPServer(("0.0.0.0", Config.LOCAL_PORT), FileTransferHandler)
    except OSError as e:
        print(f"\n{ERR} Error: Could not bind to port {Config.LOCAL_PORT}\n   {e}")
        sys.exit(1)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"\n{OK} HTTP server started on all interfaces (port {Config.LOCAL_PORT})")

    stopped = False

    def cleanup():
        nonlocal stopped
        if stopped:
            return
        stopped = True
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

    # ── QR code ──
    if tunnel_manager.lan_url and tunnel_manager.public_url:
        generate_qr_code(tunnel_manager.public_url, tunnel_manager.lan_url, no_qr=no_qr)
    elif tunnel_manager.public_url:
        generate_qr_code(tunnel_manager.public_url, no_qr=no_qr)
    else:
        generate_qr_code(tunnel_manager.lan_url, no_qr=no_qr)

    if expire_seconds:
        print(f"[*] Server is running for {expire_seconds} seconds. Press 'q' or Ctrl+C to stop.\n")
        shutdown_at = time.monotonic() + expire_seconds
    else:
        print("[*] Server is running.  Press 'q' or Ctrl+C to stop.\n")
        shutdown_at = None

    # ── wait loop ──
    try:
        while True:
            if shutdown_at and time.monotonic() >= shutdown_at:
                print("\n[*] Expiration reached. Shutting down…")
                break
            key = read_key()
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

    port_found = False
    for arg in argv:
        # Match -1234 or --1234
        if re.match(r"^--?\d{2,5}$", arg):
            try:
                p = int(arg.lstrip("-"))
                if 1 <= p <= 65535:
                    port = p
                    port_found = True
                    continue
            except ValueError:
                pass
        clean_argv.append(arg)

    # If no args at all (and no port was just stripped), return None to trigger TUI
    if not clean_argv and not port_found:
        return None, None

    # 2. Argparse Setup
    parser = argparse.ArgumentParser(
        description="qrtunnel: Elegant cross-platform file sharing via QR code.",
        usage="%(prog)s [send|receive] [files/dir] [options] [-PORT]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  qrtunnel                        # Start interactive TUI (default)
  qrtunnel send photo.jpg         # Share a file using Smart Mode
  qrtunnel send docs/ -lan -8080  # Share directory on LAN using port 8080
  qrtunnel receive ./uploads      # Receive files into a specific folder
  qrtunnel receive -ngrok         # Receive files via ngrok tunnel
""",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # SEND command
    p_send = subparsers.add_parser("send", help="Share files or directories with others")
    p_send.add_argument("files", nargs="+", help="Path to files or folders to share")

    # RECEIVE command
    p_recv = subparsers.add_parser("receive", help="Receive files from others")
    p_recv.add_argument(
        "dest", nargs="?", default=".", help="Directory to save received files (default: current)"
    )

    # Global Options
    for p in [p_send, p_recv]:
        g = p.add_argument_group("Tunneling Options")
        m = g.add_mutually_exclusive_group()
        m.add_argument(
            "-smart", action="store_true", help="Smart Mode: LAN + Public Tunnel (Auto fallback)"
        )
        m.add_argument(
            "-lan", action="store_true", help="LAN Only: Fast local transfer (same Wi-Fi)"
        )
        m.add_argument(
            "-ssh", action="store_true", help="SSH Tunnel: No-auth public link (localhost.run)"
        )
        m.add_argument(
            "-ngrok",
            action="store_true",
            help="Ngrok Tunnel: Secure public link (requires account)",
        )

        p.add_argument("--port", "-p", type=int, help="Specify port manually (e.g. -p 8080)")
        p.add_argument(
            "--no-qr",
            action="store_true",
            help="Suppress terminal QR output and print only access links",
        )
        p.add_argument("--expire", type=int, help="Auto-shutdown after N seconds")
        p.add_argument("-v", "--version", action="version", version=f"qrtunnel {__version__}")

    # 3. Parse
    if not clean_argv:
        # If user typed just "-8080", we technically have a port but no command.
        # We can't infer send/receive. Default to TUI or Error?
        # Let's print help.
        print(f"{ERR} Please specify 'send' or 'receive' command.")
        return None, None

    args = parser.parse_args(clean_argv)

    # Override port if explicitly set via --port
    if args.port:
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

    # ── TUI MODE ──
    if args is None:
        result = run_tui()
        if result is None:
            print("\n[*] Exited. Goodbye!\n")
            sys.exit(0)
        is_send, file_paths, mode_name, port = result

        # TUI already confirms, so we just launch
        if is_send and not file_paths:
            sys.stdout.write(CLEAR)
            print(f"\n{ERR} No files selected. Please re-run and select at least one file.\n")
            sys.exit(1)
        launch_server(is_send, file_paths, mode_name, port)
        return

    # ── CLI MODE ──
    is_send = args.command == "send"

    if is_send:
        file_paths = validate_send_paths(args.files)
    else:
        # Receive mode
        target_dir = validate_receive_destination(args.dest)
        os.chdir(target_dir)  # Switch to dest dir for receiving
        file_paths = []

    # Determine Mode
    mode_name = "Smart"
    if args.lan:
        mode_name = "LAN"
    elif args.ssh:
        mode_name = "SSH"
    elif args.ngrok:
        mode_name = "Ngrok"

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
    )
