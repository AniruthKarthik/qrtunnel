"""Public tunnel providers and tunnel selection."""

import json
import platform
import re
import subprocess
import threading
import time

from .config import Config
from .constants import ERR, OK
from .utils import get_lan_ip


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
        self.name = "localhost.run"
        self.output_thread = None
        self.url_found = threading.Event()

    def check_ssh(self):
        try:
            subprocess.run(["ssh", "-V"], capture_output=True, timeout=2)
            return True
        except Exception:
            return False

    def _read_output(self):
        url_pattern = re.compile(r"https://[a-zA-Z0-9.-]+\.lhr\.life")
        try:
            while self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                line = line.strip()
                if line:
                    match = url_pattern.search(line)
                    if match and not self.public_url:
                        self.public_url = match.group(0)
                        self.url_found.set()
        except Exception:
            pass

    def start(self):
        if not self.check_ssh():
            print(f"[!] SSH not available, skipping {self.name}")
            return False
        print(f"[*] Trying {self.name} (no auth required)...")

        # Use platform-appropriate null device
        null_device = "NUL" if platform.system() == "Windows" else "/dev/null"

        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"UserKnownHostsFile={null_device}",
            "-o",
            "ServerAliveInterval=60",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "AddressFamily=inet",
            "-T",
            "-R",
            f"80:localhost:{self.local_port}",
            "nokey@localhost.run",
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
            if self.url_found.wait(timeout=20):
                print(f"{OK} Connected via {self.name}: {self.public_url}")
                return True
            else:
                print(f"[!] {self.name} timeout - no URL received")
                self.stop()
                return False
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
            print("\n[*] SSH tunnel closed")


class CloudflareTunnel:
    def __init__(self, local_port):
        self.local_port = local_port
        self.process = None
        self.public_url = None
        self.name = "cloudflared"
        self.output_thread = None
        self.url_found = threading.Event()

    def check_cloudflared(self):
        try:
            subprocess.run(["cloudflared", "--version"], capture_output=True, timeout=2)
            return True
        except Exception:
            return False

    def _read_output(self):
        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        try:
            while self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                match = url_pattern.search(line.strip())
                if match and not self.public_url:
                    self.public_url = match.group(0)
                    self.url_found.set()
        except Exception:
            pass

    def start(self):
        if not self.check_cloudflared():
            print(f"[!] {self.name} not available, skipping Cloudflare Tunnel")
            return False
        print(f"[*] Trying {self.name} (no auth required)...")
        cmd = ["cloudflared", "tunnel", "--url", f"http://localhost:{self.local_port}"]
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
            if self.url_found.wait(timeout=20):
                print(f"{OK} Connected via {self.name}: {self.public_url}")
                return True
            print(f"[!] {self.name} timeout - no URL received")
            self.stop()
            return False
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
        self.tunnel_backend = tunnel_backend

    def _try_tunnel(self, tunnel):
        if tunnel.start():
            self.active_tunnel = tunnel
            self.public_url = tunnel.public_url
            return True
        return False

    def start(self):
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
                print(f"{ERR} Error: Could not detect LAN IP address.")
                print("  Make sure you are connected to a Wi-Fi or local network.")
                print("=" * 60)
                return False

        print("\n" + "=" * 60)
        if self.lan_ip:
            print("SMART MODE ENABLED (LAN + Tunnel)")
        else:
            print("ESTABLISHING PUBLIC TUNNEL")
        print("=" * 60)

        success = False
        if self.tunnel_backend == "ngrok":
            success = False
        elif self.tunnel_backend == "cloudflare":
            success = self._try_tunnel(CloudflareTunnel(self.local_port))
        elif self.noauth:
            success = self._try_tunnel(SSHTunnel(self.local_port))
            if not success:
                print("\n[!] No-auth SSH tunnel failed. Trying Cloudflare Tunnel...")
                success = self._try_tunnel(CloudflareTunnel(self.local_port))

        if not success:
            ngrok_tunnel = NgrokTunnel(self.local_port, self.auth_manager)
            if ngrok_tunnel.start():
                self.active_tunnel = ngrok_tunnel
                self.public_url = ngrok_tunnel.public_url
                success = True

        if success:
            print("=" * 60)
            return True

        if self.lan_ip:
            print("\n[!] Tunnel services failed. Continuing in LAN-only mode.")
            print("=" * 60)
            return True

        print("=" * 60)
        print(f"\n{ERR} All connection services failed")
        return False

    def stop(self):
        if self.active_tunnel:
            self.active_tunnel.stop()

