"""Public tunnel providers and tunnel selection."""

import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from .config import Config
from .constants import ERR, INFO, OK
from .utils import get_lan_ip


def get_windows_ngrok_install_hint():
    if platform.system() != "Windows":
        return None
    try:
        subprocess.run(["winget", "--version"], capture_output=True, timeout=2)
        return "Install ngrok with: winget install ngrok.ngrok"
    except Exception:
        return "Download ngrok from: https://ngrok.com/download"


def print_windows_ngrok_install_hint():
    hint = get_windows_ngrok_install_hint()
    if hint:
        print(f"   {hint}")


def get_cloudflared_path():
    """Locate cloudflared binary in PATH, ~/.local/bin, or ~/.qrtunnel/bin."""
    found = shutil.which("cloudflared")
    if found:
        return found
    home = Path.home()
    is_win = platform.system() == "Windows"
    filename = "cloudflared.exe" if is_win else "cloudflared"
    candidates = [
        home / ".local" / "bin" / filename,
        home / ".qrtunnel" / "bin" / filename,
    ]
    for c in candidates:
        if c.is_file() and (is_win or os.access(str(c), os.X_OK)):
            return str(c)
    return None


def ensure_cloudflared():
    """Ensure cloudflared is available; automatically downloads static binary if missing."""
    existing = get_cloudflared_path()
    if existing:
        return existing

    system = platform.system().lower()
    machine = platform.machine().lower()
    url = None

    if system == "linux":
        if machine in ("x86_64", "amd64"):
            url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
        elif machine in ("aarch64", "arm64"):
            url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
    elif system == "windows":
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

    if not url:
        return None

    dest_dir = Path.home() / ".qrtunnel" / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / ("cloudflared.exe" if system == "windows" else "cloudflared")

    try:
        print("[*] Downloading official cloudflared binary...")
        urllib.request.urlretrieve(url, str(dest_file))
        if system != "windows":
            dest_file.chmod(0o755)
        print(f"{OK} cloudflared downloaded to {dest_file}")
        return str(dest_file)
    except Exception as e:
        print(f"[!] Could not download cloudflared: {e}")
        return None


def get_ssh_key_args():
    """Ensure an SSH key exists for nokey SSH tunneling; generates one if missing."""
    home = Path.home()
    ssh_dir = home / ".ssh"
    default_keys = ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]
    for k in default_keys:
        if (ssh_dir / k).is_file():
            return []  # OpenSSH uses default key

    qrtunnel_key = home / ".qrtunnel" / "id_ed25519"
    if qrtunnel_key.is_file():
        return ["-i", str(qrtunnel_key)]

    try:
        qrtunnel_dir = home / ".qrtunnel"
        qrtunnel_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(qrtunnel_key)],
            capture_output=True,
            timeout=5,
        )
        if qrtunnel_key.is_file():
            return ["-i", str(qrtunnel_key)]
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────
#  NGROK / SSH / TUNNEL  (preserved exactly)
# ─────────────────────────────────────────────────────────
class NgrokAuth:
    def __init__(self):
        self.config_dir = Config.CONFIG_DIR
        self.config_file = Config.CONFIG_FILE

    def ensure_config_dir(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_config(self, config):
        self.ensure_config_dir()
        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

    def get_authtoken(self):
        return self.load_config().get("ngrok_authtoken")

    def save_authtoken(self, token):
        config = self.load_config()
        config["ngrok_authtoken"] = token
        self.save_config(config)

    def setup_ngrok_account(self):
        print("\n" + "=" * 60)
        print("NGROK ACCOUNT SETUP")
        print("=" * 60)
        print("\nNgrok is a reliable tunneling service that works on all platforms.")
        print("\n🔑 To get your ngrok authtoken:")
        print("   1. Visit: https://dashboard.ngrok.com/signup")
        print("   2. Sign up for a FREE account (email required)")
        print(
            "   3. Copy your authtoken from: https://dashboard.ngrok.com/get-started/your-authtoken"
        )
        if platform.system() != "Windows":
            print("\n" + "-" * 60)
            print("💡 TIP: No Sign-up Required by Default")
            print("-" * 60)
            print("On Linux/macOS, qrtunnel uses SSH tunneling by default.")
            print("You only need to set up ngrok if you specifically want to use it.")
            print("-" * 60)
        print("\n" + "=" * 60)
        choice = input("\nDo you have an ngrok authtoken? (y/n): ").strip().lower()
        if choice == "y":
            print("\n📋 Paste your ngrok authtoken below:")
            authtoken = input("Authtoken: ").strip()
            if authtoken and len(authtoken) > 20:
                self.save_authtoken(authtoken)
                print(f"\n{OK} Authtoken saved successfully!")
                print(f"   Config location: {self.config_file}")
                return authtoken
            else:
                print(f"\n{ERR} Invalid authtoken. Please try again.")
                return None
        else:
            print("\n[OPTIONS]:")
            print("  1. Sign up at: https://dashboard.ngrok.com/signup")
            print("  2. Run 'qrtunnel --setup' after you get your authtoken")
            if platform.system() != "Windows":
                print("  3. OR use default SSH mode (no sign-up needed!)")
            return None

    def verify_token(self, token):
        try:
            from pyngrok import ngrok

            ngrok.set_auth_token(token)
            return True
        except Exception as e:
            print(f"{ERR} Token verification failed: {e}")
            return False


class NgrokTunnel:
    def __init__(self, local_port, auth_manager):
        self.local_port = local_port
        self.auth_manager = auth_manager
        self.public_url = None
        self.tunnel = None
        self.name = "ngrok"

    def start(self):
        try:
            from pyngrok import conf, ngrok

            print("\n[*] Starting ngrok tunnel...")
            authtoken = self.auth_manager.get_authtoken()
            if not authtoken:
                print("[!] No ngrok authtoken found")
                if platform.system() != "Windows":
                    print("\n💡 TIP: You can skip ngrok sign-up!")
                    print("   Simply choose SSH mode instead.\n")
                authtoken = self.auth_manager.setup_ngrok_account()
                if not authtoken:
                    print("[!] Cannot start ngrok without authtoken")
                    return False
            try:
                ngrok.set_auth_token(authtoken)
            except Exception as e:
                print(f"[!] Error setting authtoken: {e}")
                authtoken = self.auth_manager.setup_ngrok_account()
                if not authtoken:
                    return False
                ngrok.set_auth_token(authtoken)
            conf.get_default().log_level = "ERROR"
            print("[*] Establishing tunnel...")
            self.tunnel = ngrok.connect(self.local_port, bind_tls=True)
            self.public_url = self.tunnel.public_url
            if self.public_url.startswith("http://"):
                self.public_url = self.public_url.replace("http://", "https://")
            print(f"{OK} Tunnel established: {self.public_url}")
            return True
        except ImportError:
            print(f"{ERR} Error: pyngrok is not installed")
            print("   Install with: pip install pyngrok")
            print_windows_ngrok_install_hint()
            return False
        except Exception as e:
            error_msg = str(e).lower()
            if "authtoken" in error_msg or "unauthorized" in error_msg or "invalid" in error_msg:
                print(f"{ERR} Authentication error: {e}")
                print("[*] Your authtoken might be invalid or expired.")
                authtoken = self.auth_manager.setup_ngrok_account()
                if authtoken:
                    try:
                        from pyngrok import ngrok

                        ngrok.set_auth_token(authtoken)
                        self.tunnel = ngrok.connect(self.local_port, bind_tls=True)
                        self.public_url = self.tunnel.public_url
                        if self.public_url.startswith("http://"):
                            self.public_url = self.public_url.replace("http://", "https://")
                        print(f"{OK} Tunnel established: {self.public_url}")
                        return True
                    except Exception as retry_error:
                        print(f"{ERR} Still failed: {retry_error}")
                        return False
                return False
            else:
                print(f"{ERR} Error starting ngrok: {e}")
                if "ngrok" in error_msg and (
                    "not found" in error_msg or "no such file" in error_msg
                ):
                    print_windows_ngrok_install_hint()
                return False

    def stop(self):
        if self.tunnel:
            try:
                from pyngrok import ngrok

                ngrok.disconnect(self.tunnel.public_url)
                print("\n[*] Ngrok tunnel closed")
            except Exception:
                pass


class SSHTunnel:
    def __init__(self, local_port):
        self.local_port = local_port
        self.process = None
        self.public_url = None
        self.name = "SSH Tunnel"
        self.output_thread = None
        self.url_found = threading.Event()

    def check_ssh(self):
        try:
            subprocess.run(["ssh", "-V"], capture_output=True, timeout=2)
            return True
        except Exception:
            return False

    def _read_output(self):
        url_pattern = re.compile(
            r"https://[a-zA-Z0-9.-]+(?:\.lhr\.life|\.localhost\.run|\.free\.pinggy\.net|\.run\.pinggy-free\.link|\.pinggy\.net|\.pinggy\.link)"
        )
        try:
            while self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                clean_line = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line).strip()
                if clean_line:
                    match = url_pattern.search(clean_line)
                    if match and not self.public_url:
                        self.public_url = match.group(0)
                        self.url_found.set()
        except Exception:
            pass

    def _try_provider(self, provider_name, cmd, timeout=12):
        self.public_url = None
        self.url_found.clear()
        print(f"[*] Trying {provider_name} (no auth required)...")
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self.output_thread = threading.Thread(target=self._read_output, daemon=True)
            self.output_thread.start()
            if self.url_found.wait(timeout=timeout):
                print(f"{OK} Connected via {provider_name}: {self.public_url}")
                return True
            else:
                print(f"[!] {provider_name} timeout - no URL received")
                self.stop()
                return False
        except Exception as e:
            print(f"[!] {provider_name} error: {e}")
            self.stop()
            return False

    def start(self):
        if not self.check_ssh():
            print(f"[!] SSH not available, skipping {self.name}")
            return False

        null_device = "NUL" if platform.system() == "Windows" else "/dev/null"
        key_args = get_ssh_key_args()

        # 1. Primary provider: localhost.run
        cmd_lhr = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"UserKnownHostsFile={null_device}",
            "-o",
            "ServerAliveInterval=60",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "AddressFamily=inet",
            *key_args,
            "-T",
            "-R",
            f"80:localhost:{self.local_port}",
            "nokey@localhost.run",
        ]
        if self._try_provider("localhost.run", cmd_lhr, timeout=12):
            return True

        # 2. Fallback provider: pinggy.io (port 443 / HTTPS port - works through restricted firewalls)
        cmd_pinggy = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"UserKnownHostsFile={null_device}",
            "-o",
            "ServerAliveInterval=60",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "LogLevel=ERROR",
            *key_args,
            "-p",
            "443",
            "-R0:localhost:{self.local_port}",
            "a.pinggy.io",
        ]
        if self._try_provider("pinggy.io (port 443)", cmd_pinggy, timeout=12):
            return True

        return False

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
            print("\n[*] SSH tunnel closed")


class CloudflareTunnel:
    def __init__(self, local_port):
        self.local_port = local_port
        self.process = None
        self.public_url = None
        self.name = "cloudflared"
        self.output_thread = None
        self.url_found = threading.Event()
        self.connection_registered = threading.Event()
        self.connection_failed = threading.Event()
        self.fail_count = 0
        self.bin_path = get_cloudflared_path() or "cloudflared"

    def check_cloudflared(self):
        path = get_cloudflared_path()
        if path:
            self.bin_path = path
            return True
        try:
            subprocess.run([self.bin_path, "--version"], capture_output=True, timeout=2)
            return True
        except Exception:
            return False

    def _read_output(self):
        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        reg_pattern = re.compile(
            r"(?:Registered tunnel connection|Connection [a-f0-9-]+ registered|registered connIndex=\d+)",
            re.IGNORECASE,
        )
        fail_pattern = re.compile(
            r"(?:Unable to establish connection with Cloudflare edge|failed to dial to edge with quic|connect: connection refused|Serve tunnel error.*:7844|failed to dial to edge)",
            re.IGNORECASE,
        )
        try:
            while self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                clean_line = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line).strip()
                if not clean_line:
                    continue

                # 1. Capture public tunnel URL
                match = url_pattern.search(clean_line)
                if match and not self.public_url:
                    self.public_url = match.group(0)
                    self.url_found.set()

                # 2. Check for successful edge connection registration
                if reg_pattern.search(clean_line):
                    self.connection_registered.set()

                # 3. Detect edge dial failures (port 7844 refused / blocked)
                if fail_pattern.search(clean_line):
                    self.fail_count += 1
                    if self.fail_count >= 1:
                        self.connection_failed.set()
        except Exception:
            pass

    def start(self):
        if not self.check_cloudflared():
            ensured = ensure_cloudflared()
            if ensured:
                self.bin_path = ensured
            else:
                print(f"[!] {self.name} not available, skipping Cloudflare Tunnel")
                return False

        self.public_url = None
        self.url_found.clear()
        self.connection_registered.clear()
        self.connection_failed.clear()
        self.fail_count = 0

        print(f"[*] Trying {self.name} (no auth required)...")
        cmd = [
            self.bin_path,
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{self.local_port}",
        ]
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self.output_thread = threading.Thread(target=self._read_output, daemon=True)
            self.output_thread.start()

            # Wait for public URL banner
            if not self.url_found.wait(timeout=20):
                print(
                    f"[!] {self.name} timeout - no URL received (check your internet or if cloudflared is blocked)"
                )
                self.stop()
                return False

            # URL received from trycloudflare banner; now verify edge connector registration
            # to prevent broken URLs leading to Cloudflare Error 1033 (HTTP 530)
            start_t = time.time()
            while time.time() - start_t < 7.0:
                if self.connection_registered.is_set():
                    break
                if self.connection_failed.is_set() and (time.time() - start_t > 2.5):
                    break
                if self.process and self.process.poll() is not None:
                    break
                time.sleep(0.2)

            if not self.connection_registered.is_set():
                print(
                    "[!] Cloudflare edge unreachable (port 7844 blocked or connection refused)."
                )
                print(
                    "[!] Aborting Cloudflare tunnel to prevent Cloudflare Error 1033."
                )
                self.stop()
                return False

            print(f"{OK} Connected via {self.name}: {self.public_url}")
            return True
        except Exception as e:
            print(f"[!] {self.name} error: {e}")
            self.stop()
            return False

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
            self.public_url = None
            print("\n[*] Cloudflare tunnel closed")


class TunnelManager:
    def __init__(self, local_port, noauth=False, lan_only=False, lan_ip=None, tunnel_backend=None):
        self.local_port = local_port
        self.active_tunnel = None
        self.public_url = None
        self.lan_url = None
        self.lan_ip = lan_ip
        self.auth_manager = NgrokAuth()
        self.noauth = noauth
        self.lan_only = lan_only
        self.tunnel_backend = tunnel_backend.lower() if tunnel_backend else None
        self.fallback_to_lan = False
        self.fell_back_to_ssh = False
        self.fell_back_to_cloudflare = False

    def _try_tunnel(self, tunnel):
        if tunnel.start():
            self.active_tunnel = tunnel
            self.public_url = tunnel.public_url
            return True
        return False

    def start(self):
        self.fallback_to_lan = False
        if not self.lan_ip:
            self.lan_ip = get_lan_ip()
        if self.lan_ip:
            self.lan_url = f"http://{self.lan_ip}:{self.local_port}"

        if self.lan_only:
            print("\n" + "=" * 60)
            print("LAN MODE ACTIVE")
            print("=" * 60)
            if self.lan_ip:
                print(f"{OK} LAN server active: {self.lan_url}")
                print("=" * 60)
                return True
            else:
                print(
                    f"{INFO} Not in same LAN (no local network detected), "
                    "switching to the other connection..."
                )
                print("=" * 60)
                self.lan_only = False

        print("\n" + "=" * 60)
        print("ESTABLISHING PUBLIC TUNNEL")
        print("=" * 60)

        success = False
        if self.tunnel_backend == "cloudflare":
            success = self._try_tunnel(CloudflareTunnel(self.local_port))
            if not success:
                print("\n[!] Cloudflare tunnel failed (port 7844 blocked or Error 1033).")
                print("[*] Automatically falling back to SSH tunnel (ports 22/443, no sign-up required)...")
                if self._try_tunnel(SSHTunnel(self.local_port)):
                    success = True
                    self.fell_back_to_ssh = True
        elif self.tunnel_backend == "ssh":
            success = self._try_tunnel(SSHTunnel(self.local_port))
            if not success:
                print("\n[!] SSH tunnel failed. Trying Cloudflare tunnel fallback...")
                if self._try_tunnel(CloudflareTunnel(self.local_port)):
                    success = True
                    self.fell_back_to_cloudflare = True
        elif self.tunnel_backend == "ngrok":
            ngrok_tunnel = NgrokTunnel(self.local_port, self.auth_manager)
            success = self._try_tunnel(ngrok_tunnel)
        elif self.noauth:
            success = self._try_tunnel(SSHTunnel(self.local_port))
            if not success and self.tunnel_backend is None:
                # Fallback: try Cloudflare if installed
                success = self._try_tunnel(CloudflareTunnel(self.local_port))

        if not success and self.tunnel_backend not in ("cloudflare", "ssh", "ngrok"):
            ngrok_tunnel = NgrokTunnel(self.local_port, self.auth_manager)
            if self._try_tunnel(ngrok_tunnel):
                success = True

        if success:
            print("=" * 60)
            return True

        if self.lan_ip:
            self.fallback_to_lan = True
            print("\n[!] Tunnel services failed. Continuing in LAN-only mode.")
            print("=" * 60)
            return True

        print("=" * 60)
        print(f"\n{ERR} All connection services failed")
        return False

    def stop(self):
        if self.active_tunnel:
            try:
                self.active_tunnel.stop()
            except Exception:
                pass
            self.active_tunnel = None
        self.public_url = None

