#!/usr/bin/env python3
"""
qrtunnel: Simple cross-platform file sharing via QR code.
Features account-free SSH tunneling (default on Linux/macOS) and ngrok support.
Now with a fully interactive arrow-key TUI.

Smart Mode Limitations:
- AP Isolation: Some guest Wi-Fi networks prevent devices from talking to each other.
- Firewalls: The host computer must allow incoming traffic on the local port (default 8000).
- Subnets/VLANs: Heuristic assumes a /24 subnet. If client and server are on different
  local subnets, Smart Mode will correctly fall back to the Internet tunnel.
- VPNs: Active VPNs may interfere with LAN IP detection or routing.
"""

__version__ = "3.5.2"

import argparse
import http.cookies
import ipaddress
import json
import os
import platform
import random
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse

from streaming_form_data import StreamingFormDataParser
from streaming_form_data.targets import FileTarget
from werkzeug.wsgi import LimitedStream

# ─────────────────────────────────────────────────────────
#  TERMINAL COLOURS & ICONS (Neat Palette)
# ─────────────────────────────────────────────────────────
CLR_G = "\033[32m"  # Standard Green (Success/Selected)
CLR_Y = "\033[93m"  # Bright Yellow (Warnings/Focus)
CLR_R = "\033[31m"  # Standard Red (Errors)
CLR_B = "\033[34m"  # Standard Blue (Info)
CLR_C = "\033[36m"  # Standard Cyan (Directories)
CLR_M = "\033[35m"  # Standard Magenta (Headers)
CLR_W = "\033[37m"  # Standard White
CLR_DIM = "\033[90m"  # Bright Black (Grey)
CLR_BLD = "\033[1m"  # Bold
CLR_RST = "\033[0m"  # Reset
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR = "\033[2J\033[H"

DOT = "●"
OK = f"{CLR_G}{DOT}{CLR_RST}"
ERR = f"{CLR_R}{DOT}{CLR_RST}"
WRN = f"{CLR_Y}{DOT}{CLR_RST}"
INFO = f"{CLR_B}{DOT}{CLR_RST}"

W = 64  # panel width


# ─────────────────────────────────────────────────────────
#  LOW-LEVEL KEYBOARD READING  (cross-platform)
# ─────────────────────────────────────────────────────────
def _read_key_unix():
    """Blocking single-key read on Unix; returns a string token."""
    import os
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()

    # Check if canonical mode is enabled (cooked) or disabled (raw)
    # lflags is the 4th element (index 3)
    try:
        attrs = termios.tcgetattr(fd)
        is_canonical = attrs[3] & termios.ICANON
    except:
        is_canonical = True  # Assume cooked if we can't tell

    try:
        if is_canonical:
            # Switch to cbreak mode temporarily (raw input, but processed output)
            # This prevents "staircase" printing when other threads print to stdout
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd, termios.TCSADRAIN)

        # Select on the FILE DESCRIPTOR, not the sys.stdin object
        if not select.select([fd], [], [], 0.15)[0]:
            return None

        # Read raw bytes from FD to avoid Python buffering issues
        try:
            b = os.read(fd, 1)
        except OSError:
            return None

        if not b:
            return None

        # Simple decode
        try:
            ch = b.decode()
        except UnicodeDecodeError:
            return None

        if ch == "\x1b":
            # possible escape sequence – read more if available
            # 0.1s timeout should be plenty for local or ssh
            if select.select([fd], [], [], 0.1)[0]:
                b2 = os.read(fd, 1)
                ch2 = b2.decode(errors="ignore")

                # Handle '[' (CSI) and 'O' (SS3)
                if ch2 == "[" or ch2 == "O":
                    if select.select([fd], [], [], 0.1)[0]:
                        b3 = os.read(fd, 1)
                        ch3 = b3.decode(errors="ignore")

                        if ch3 == "A":
                            return "UP"
                        if ch3 == "B":
                            return "DOWN"
                        if ch3 == "C":
                            return "RIGHT"
                        if ch3 == "D":
                            return "LEFT"
                        if ch2 == "[" and ch3 == "~":
                            return "FUNC"
                        return None
                    return None
                return None
            return "ESC"
        if ch == "\r" or ch == "\n":
            return "ENTER"
        if ch == " ":
            return "SPACE"
        if ch == "\x7f" or ch == "\x08":
            return "BACKSPACE"
        if ch == "\x03":
            return "CTRL_C"
        if ch.isprintable():
            return ch
        return None

    finally:
        if is_canonical:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key_win():
    """Blocking single-key read on Windows."""
    import msvcrt

    ch = msvcrt.getch()
    if ch in (b"\xe0", b"\x00"):
        ch2 = msvcrt.getch()
        codes = {72: "UP", 80: "DOWN", 77: "RIGHT", 75: "LEFT"}
        return codes.get(ch2[0] if isinstance(ch2, bytes) else ch2)
    if ch in (b"\r", b"\n"):
        return "ENTER"
    if ch == b" ":
        return "SPACE"
    if ch in (b"\x7f", b"\x08"):
        return "BACKSPACE"
    if ch == b"\x03":
        return "CTRL_C"
    try:
        c = ch.decode()
        if c.isprintable():
            return c
    except:
        pass
    return None


def read_key():
    """Cross-platform blocking key reader.  Returns a string token or None."""
    if platform.system() == "Windows":
        return _read_key_win()
    return _read_key_unix()


# ─────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────
class Config:
    LOCAL_PORT = 8000
    OTP = None
    CONFIG_DIR = Path.home() / ".qrtunnel"
    CONFIG_FILE = CONFIG_DIR / "config.json"


# ─────────────────────────────────────────────────────────
#  HELPERS  (preserved from original)
# ─────────────────────────────────────────────────────────
def format_size(b):
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} TB"


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        addr = ipaddress.ip_address(ip)
        if addr.is_private and not addr.is_loopback:
            return str(ip)
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            addr = ipaddress.ip_address(ip)
            if addr.is_private and not addr.is_loopback:
                return str(ip)
    except Exception:
        pass
    return None


def is_same_lan(client_ip, server_ip):
    try:
        c_ip = ipaddress.ip_address(client_ip)
        s_ip = ipaddress.ip_address(server_ip)
        if not (c_ip.is_private and s_ip.is_private):
            return False
        if c_ip == s_ip:
            return True
        if platform.system() == "Linux":
            try:
                with open("/proc/net/arp") as f:
                    if client_ip in f.read():
                        return True
            except:
                pass
        c_net = ipaddress.ip_network(f"{client_ip}/24", strict=False)
        return s_ip in c_net
    except:
        return False


# ─────────────────────────────────────────────────────────
#  HOTSPOT HELPER  (preserved)
# ─────────────────────────────────────────────────────────
class HotspotHelper:
    def __init__(self):
        self.config_file = Config.CONFIG_FILE

    def load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_config(self, config):
        Config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

    def setup_interactive(self):
        print("\n" + "=" * 60)
        print("WI-FI HOTSPOT SETUP")
        print("=" * 60)
        try:
            ssid = input("SSID (Network Name): ").strip()
            if not ssid:
                print(f"{ERR} SSID cannot be empty.")
                return
            print("\nSecurity Type:")
            print("  1. WPA/WPA2/WPA3 (Most common)")
            print("  2. WEP (Old)")
            print("  3. None (Open)")
            sec_choice = input("Select [1-3] (default 1): ").strip()
            security = "WPA"
            if sec_choice == "2":
                security = "WEP"
            elif sec_choice == "3":
                security = "nopass"
            password = ""
            if security != "nopass":
                password = input("Password: ").strip()
            config = self.load_config()
            config["hotspot"] = {"ssid": ssid, "password": password, "security": security}
            self.save_config(config)
            print(f"\n{OK} Hotspot configuration saved.")
        except KeyboardInterrupt:
            print("\n\n[*] Setup cancelled.")

    def get_qr_data(self):
        config = self.load_config().get("hotspot")
        if not config:
            return None
        ssid = config.get("ssid")
        password = config.get("password", "")
        security = config.get("security", "WPA")
        if not ssid:
            return None

        def escape(s):
            return (
                s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace(":", "\\:")
            )

        qr_str = f"WIFI:T:{security};S:{escape(ssid)};"
        if security != "nopass":
            qr_str += f"P:{escape(password)};"
        qr_str += "H:false;;"
        return qr_str, ssid, password


# ─────────────────────────────────────────────────────────
#  HTTP SERVER  (all classes preserved exactly)
# ─────────────────────────────────────────────────────────
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class FileTransferHandler(BaseHTTPRequestHandler):
    file_paths = None
    upload_mode = False
    server_lan_ip = None
    authorized_sessions = set()

    # ── auth ──
    def check_auth(self):
        if self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        if self.path == "/ping" or self.path.startswith("/ping?"):
            return True
        cookie_header = self.headers.get("Cookie")
        if cookie_header:
            try:
                cookies = http.cookies.SimpleCookie(cookie_header)
                if "session" in cookies:
                    if cookies["session"].value in self.authorized_sessions:
                        return True
            except:
                pass
        return False

    def handle_login(self):
        try:
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length).decode("utf-8")
            from urllib.parse import parse_qs

            params = parse_qs(post_data)
            password = params.get("password", [""])[0]
            if password == Config.OTP:
                session_token = str(uuid.uuid4())
                self.authorized_sessions.add(session_token)
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header(
                    "Set-Cookie", f"session={session_token}; Path=/; HttpOnly; Max-Age=86400"
                )
                self.end_headers()
                print(f"{OK} Auth success from {self.client_address[0]}")
            else:
                print(f"{WRN} Failed auth attempt from {self.client_address[0]}")
                self.send_login_page(error="Incorrect password")
        except Exception as e:
            print(f"{ERR} Auth error: {e}")
            self.send_error(500, "Internal Server Error")

    def send_login_page(self, error=None):
        error_html = f'<p class="error">{error}</p>' if error else ""
        html = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>qrtunnel - Security Check</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; background: #1a1a2e; color: #eee;
       display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
.box {{ background: #16213e; padding: 40px; border-radius: 8px; text-align: center;
        width: 100%; max-width: 320px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }}
input {{ width: 100%; padding: 12px; margin: 20px 0; background: #0f0f1a; border: 1px solid #2a3a5e;
         color: white; border-radius: 4px; font-size: 18px; text-align: center; letter-spacing: 2px; }}
button {{ width: 100%; padding: 12px; background: #4361ee; color: white; border: none;
          border-radius: 4px; font-size: 16px; cursor: pointer; }}
button:hover {{ background: #3a56d4; }}
.error {{ color: #ff4757; margin-bottom: 10px; }}
h2 {{ margin-top: 0; }}
</style></head><body>
<div class="box">
<h2>🔒 Restricted Access</h2>
<p>Please enter the 6-digit code shown on the host screen.</p>
{error_html}
<form action="/login" method="post">
<input type="text" name="password" pattern="[0-9]*" inputmode="numeric"
       placeholder="000000" maxlength="6" required autofocus autocomplete="off">
<button type="submit">Verify</button>
</form>
</div></body></html>"""
        self.send_response(200 if not error else 403)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html.encode())

    # ── logging ──
    def log_message(self, format, *args):
        client_ip = self.client_address[0]

        # Check for forwarded IP (tunnels)
        forwarded_for = self.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can be a list, take the first one
            real_ip = forwarded_for.split(",")[0].strip()
            conn_type = f"{INFO} Tunnel"
            display_ip = real_ip
        else:
            is_local = client_ip in ("127.0.0.1", "::1")
            if is_local:
                conn_type = f"{OK} Local"
                display_ip = "localhost"
            elif self.server_lan_ip and is_same_lan(client_ip, self.server_lan_ip):
                conn_type = f"{OK} LAN"
                display_ip = client_ip
            else:
                conn_type = f"{INFO} Tunnel"
                display_ip = client_ip

        path = self.path
        if "/download/" in path or "/upload" in path or path == "/":
            print(f"\r[*] {conn_type} request from {display_ip}: {path}")

    # ── routing ──
    def do_GET(self):
        if not self.check_auth():
            self.send_login_page()
            return
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/ping":
            self.send_ping_gif()
        elif self.upload_mode:
            self.send_upload_page()
        else:
            if parsed_path.path.startswith("/download/"):
                self.serve_single_file(unquote(parsed_path.path[len("/download/") :]))
            elif parsed_path.path in ("/", "/index.html"):
                self.send_download_page()
            else:
                self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path == "/login":
            self.handle_login()
            return
        if not self.check_auth():
            self.send_login_page()
            return
        if self.upload_mode:
            self.handle_upload()
        else:
            self.send_error(405, "Method Not Allowed")

    # ── ping ──
    def send_ping_gif(self):
        gif = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        self.send_response(200)
        self.send_header("Content-type", "image/gif")
        self.send_header("Content-Length", len(gif))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(gif)

    # ── smart redirect JS ──
    def get_smart_redirect_js(self):
        lan_ip = str(self.server_lan_ip) if self.server_lan_ip else ""
        if not lan_ip or lan_ip in ("None", "127.0.0.1"):
            return ""
        return f"""
    <script>
        (function() {{
            var lanIp = "{lan_ip}";
            var lanPort = {Config.LOCAL_PORT};
            var lanUrl = "http://" + lanIp + ":" + lanPort;
            if (window.location.hostname !== lanIp) {{
                var img = new Image();
                img.onload = function() {{
                    setTimeout(function() {{
                        window.location.href = lanUrl + window.location.pathname + window.location.search;
                    }}, 100);
                }};
                img.src = lanUrl + "/ping?t=" + Date.now();
            }}
        }})();
    </script>"""

    # ── upload handler ──
    def handle_upload(self):
        try:
            content_length = int(self.headers["Content-Length"])
            stream = LimitedStream(self.rfile, content_length)
            parser = StreamingFormDataParser(headers=self.headers)
            temp_filename = f"upload_{int(time.time())}.tmp"
            temp_path = Path.cwd() / temp_filename
            file_target = FileTarget(str(temp_path))
            parser.register("file", file_target)
            chunk_size = 65536
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                parser.data_received(chunk)
            if not getattr(file_target, "multipart_filename", None):
                self.send_error(400, "File not found in form data")
                return
            sanitized_filename = os.path.basename(unquote(file_target.multipart_filename))
            if not sanitized_filename:
                self.send_error(400, "Invalid filename")
                return
            final_path = Path.cwd() / sanitized_filename
            os.rename(temp_path, final_path)
            print(f"{OK} File '{sanitized_filename}' received and saved to {final_path}")
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            success_html = self.get_upload_success_page(sanitized_filename)
            self.send_header("Content-Length", str(len(success_html)))
            self.end_headers()
            self.wfile.write(success_html.encode())
            self.close_connection = True
        except Exception as e:
            print(f"{ERR} Error during upload: {e}")
            self.send_error(500, "Internal Server Error")

    def get_upload_success_page(self, filename):
        return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>qrtunnel - Upload Success</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        background:#1a1a2e; min-height:100vh; display:flex; align-items:center;
        justify-content:center; padding:20px; color:#eee; }}
.container {{ background:#16213e; border-radius:8px; padding:40px;
              box-shadow:0 4px 20px rgba(0,0,0,0.4); max-width:480px; width:100%; }}
.header {{ text-align:center; margin-bottom:32px; padding-bottom:24px; border-bottom:1px solid #2a3a5e; }}
h1 {{ font-size:24px; font-weight:600; margin-bottom:8px; color:#fff; }}
.success-message {{ text-align:center; margin-bottom:20px; color:#4CAF50; font-size:1.2em; }}
.link-button {{ display:block; width:100%; padding:16px 24px; background:#4361ee; color:#fff;
                border:none; border-radius:6px; font-size:15px; font-weight:500; cursor:pointer;
                text-decoration:none; text-align:center; transition:background 0.2s; margin-top:20px; }}
.link-button:hover {{ background:#3a56d4; }}
.footer {{ text-align:center; margin-top:24px; font-size:12px; color:#555; }}
</style></head><body>
<div class="container">
<div class="header"><h1>Upload Status</h1></div>
<div class="success-message"><p>File '<strong>{filename}</strong>' uploaded successfully!</p></div>
<a href="/" class="link-button">Upload Another File</a>
<p class="footer">qrtunnel</p>
</div></body></html>"""

    def send_upload_page(self):
        lan_ip = str(self.server_lan_ip) if self.server_lan_ip else ""
        html = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>qrtunnel - File Upload</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        background:#1a1a2e; min-height:100vh; display:flex; align-items:center;
        justify-content:center; padding:20px; color:#eee; }}
.container {{ background:#16213e; border-radius:8px; padding:40px;
              box-shadow:0 4px 20px rgba(0,0,0,0.4); max-width:480px; width:100%; }}
.header {{ text-align:center; margin-bottom:32px; padding-bottom:24px; border-bottom:1px solid #2a3a5e; }}
h1 {{ font-size:24px; font-weight:600; margin-bottom:8px; color:#fff; }}
.subtitle {{ font-size:14px; color:#888; }}
.upload-form {{ display:flex; flex-direction:column; gap:20px; }}
.file-input-wrapper {{ position:relative; width:100%; padding:16px 24px; background:#0f0f1a;
                       border:1px dashed #4361ee; border-radius:6px; text-align:center;
                       cursor:pointer; transition:background 0.2s, border-color 0.2s; }}
.file-input-wrapper:hover {{ background:#1f1f2a; border-color:#5a78ff; }}
#file-input {{ opacity:0; position:absolute; top:0; left:0; width:100%; height:100%; cursor:pointer; }}
.file-input-label {{ font-size:14px; font-weight:500; color:#ccc; }}
#file-name {{ margin-top:12px; font-size:12px; font-family:'SF Mono','Consolas',monospace; color:#888; }}
.submit-button {{ display:block; width:100%; padding:16px 24px; background:#4361ee; color:#fff;
                  border:none; border-radius:6px; font-size:15px; font-weight:500; cursor:pointer;
                  text-align:center; transition:background 0.2s; opacity:0.5; pointer-events:none; }}
.submit-button.enabled {{ opacity:1; pointer-events:auto; }}
.submit-button:hover.enabled {{ background:#3a56d4; }}
.footer {{ text-align:center; margin-top:24px; font-size:12px; color:#555; }}
</style></head><body>
<div class="container">
<div class="header"><h1>Upload File</h1><p class="subtitle">Select a file to send to this computer</p></div>
<form id="upload-form" class="upload-form" action="/upload" method="post" enctype="multipart/form-data">
<div class="file-input-wrapper">
<label for="file-input" class="file-input-label">Click to select a file</label>
<input type="file" id="file-input" name="file" required>
<p id="file-name"></p>
</div>
<button type="submit" id="submit-btn" class="submit-button">Upload</button>
</form>
<div id="lan-discovery" style="margin-top:20px;text-align:center;display:none;">
<p style="font-size:13px;color:#4CAF50;margin-bottom:10px;">Same Wi-Fi detected!</p>
<a id="lan-btn" href="#" style="font-size:14px;color:#4361ee;text-decoration:none;border:1px solid #4361ee;padding:8px 16px;border-radius:4px;">Switch to High Speed</a>
</div>
<p class="footer">qrtunnel</p>
</div>
<script>
const fileInput = document.getElementById('file-input');
const fileNameDisplay = document.getElementById('file-name');
const submitButton = document.getElementById('submit-btn');
fileInput.addEventListener('change', () => {{
    if (fileInput.files.length > 0) {{
        fileNameDisplay.textContent = 'Selected: ' + fileInput.files[0].name;
        submitButton.classList.add('enabled');
    }} else {{
        fileNameDisplay.textContent = '';
        submitButton.classList.remove('enabled');
    }}
}});
(function() {{
    var lanIp = "{lan_ip}";
    var lanPort = {Config.LOCAL_PORT};
    var lanUrl = "http://" + lanIp + ":" + lanPort;
    if (lanIp && lanIp !== "None" && window.location.hostname !== lanIp) {{
        var discoveryDiv = document.getElementById('lan-discovery');
        var lanBtn = document.getElementById('lan-btn');
        var img = new Image();
        img.onload = function() {{
            discoveryDiv.style.display = 'block';
            lanBtn.href = lanUrl + window.location.pathname + window.location.search;
        }};
        img.src = lanUrl + "/ping?t=" + Date.now();
    }}
}})();
</script>
{self.get_smart_redirect_js()}
</body></html>"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", len(html.encode()))
        self.end_headers()
        self.wfile.write(html.encode())

    # ── download page ──
    def send_download_page(self):
        lan_ip = str(self.server_lan_ip) if self.server_lan_ip else ""
        file_list_html = ""
        for fp in self.file_paths:
            fn = os.path.basename(fp)
            file_list_html += f'<li><a href="/download/{fn}" class="file-link">{fn}</a></li>'
        html = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>qrtunnel - File Download</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        background:#1a1a2e; min-height:100vh; display:flex; align-items:center;
        justify-content:center; padding:20px; color:#eee; }}
.container {{ background:#16213e; border-radius:8px; padding:40px;
              box-shadow:0 4px 20px rgba(0,0,0,0.4); max-width:480px; width:100%; }}
.header {{ text-align:center; margin-bottom:32px; padding-bottom:24px; border-bottom:1px solid #2a3a5e; }}
h1 {{ font-size:24px; font-weight:600; margin-bottom:8px; color:#fff; }}
.subtitle {{ font-size:14px; color:#888; }}
.file-section {{ margin-bottom:32px; }}
.file-section-title {{ font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#666; margin-bottom:12px; }}
.file-list {{ list-style:none; background:#0f0f1a; border-radius:6px; border:1px solid #2a3a5e; }}
.file-list li {{ border-bottom:1px solid #2a3a5e; }}
.file-list li:last-child {{ border-bottom:none; }}
.file-link {{ display:block; padding:12px 16px; font-size:14px;
              font-family:'SF Mono','Consolas',monospace; color:#ccc;
              text-decoration:none; transition:background-color 0.2s; }}
.file-link:hover {{ background-color:#2a3a5e; }}
.footer {{ text-align:center; margin-top:24px; font-size:12px; color:#555; }}
</style></head><body>
<div class="container">
<div class="header"><h1>Files Ready</h1><p class="subtitle">Click a file to download</p></div>
<div class="file-section">
<p class="file-section-title">Files ({len(self.file_paths)})</p>
<ul class="file-list">{file_list_html}</ul>
</div>
<div id="lan-discovery" style="margin-top:20px;text-align:center;display:none;">
<p style="font-size:13px;color:#4CAF50;margin-bottom:10px;">Same Wi-Fi detected!</p>
<a id="lan-btn" href="#" style="font-size:14px;color:#4361ee;text-decoration:none;border:1px solid #4361ee;padding:8px 16px;border-radius:4px;">Switch to High Speed</a>
</div>
<p class="footer">qrtunnel</p>
</div>
<script>
(function() {{
    var lanIp = "{lan_ip}";
    var lanPort = {Config.LOCAL_PORT};
    var lanUrl = "http://" + lanIp + ":" + lanPort;
    if (lanIp && lanIp !== "None" && window.location.hostname !== lanIp) {{
        var discoveryDiv = document.getElementById('lan-discovery');
        var lanBtn = document.getElementById('lan-btn');
        var img = new Image();
        img.onload = function() {{
            discoveryDiv.style.display = 'block';
            lanBtn.href = lanUrl + window.location.pathname + window.location.search;
        }};
        img.src = lanUrl + "/ping?t=" + Date.now();
    }}
}})();
</script>
{self.get_smart_redirect_js()}
</body></html>"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", len(html.encode()))
        self.end_headers()
        self.wfile.write(html.encode())

    # ── range / serve ──
    def parse_range_header(self, file_size):
        range_header = self.headers.get("Range")
        if not range_header:
            return None
        match = re.match(r"bytes=(\d+)-(\d+)?", range_header)
        if not match:
            return None
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else file_size - 1
        if start >= file_size or (end is not None and start > end):
            return False
        return start, min(end, file_size - 1)

    def serve_single_file(self, filename):
        target_path = None
        for fp in self.file_paths:
            if os.path.basename(fp) == filename:
                target_path = fp
                break
        if not target_path or not os.path.isfile(target_path):
            self.send_error(404, "File Not Found")
            return
        try:
            file_size = os.path.getsize(target_path)
            range_req = self.parse_range_header(file_size)
            if range_req is False:
                self.send_error(416, "Requested Range Not Satisfiable")
                return
            if range_req:
                start, end = range_req
                content_length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            else:
                start = 0
                end = file_size - 1
                content_length = file_size
                self.send_response(200)
            self.send_header("Content-type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(content_length))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(target_path, "rb") as f:
                if start > 0:
                    f.seek(start)
                if platform.system() == "Linux" and hasattr(os, "sendfile"):
                    try:
                        sent = 0
                        while sent < content_length:
                            n = os.sendfile(
                                self.connection.fileno(),
                                f.fileno(),
                                start + sent,
                                content_length - sent,
                            )
                            if n == 0:
                                break
                            sent += n
                    except BrokenPipeError:
                        print(f"{ERR} Client disconnected during transfer of '{filename}'")
                else:
                    try:
                        remaining = content_length
                        chunk_size = 1024 * 1024
                        while remaining > 0:
                            chunk = f.read(min(chunk_size, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    except BrokenPipeError:
                        print(f"{ERR} Client disconnected during transfer of '{filename}'")
            if not range_req or (range_req and end == file_size - 1):
                print(f"{OK} File '{filename}' served to {self.client_address[0]}")
        except Exception as e:
            if not isinstance(e, BrokenPipeError) and "Broken pipe" not in str(e):
                print(f"{ERR} Error serving file '{filename}': {e}")
                if not self.wfile.closed:
                    try:
                        self.send_error(500, "Internal Server Error")
                    except:
                        pass


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
            except:
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
            except:
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
        except:
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
        except:
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
            except:
                try:
                    self.process.kill()
                except:
                    pass
            self.process = None
            print("\n[*] SSH tunnel closed")


class TunnelManager:
    def __init__(self, local_port, noauth=False, lan_only=False, lan_ip=None):
        self.local_port = local_port
        self.active_tunnel = None
        self.public_url = None
        self.lan_url = None
        self.lan_ip = lan_ip
        self.auth_manager = NgrokAuth()
        self.noauth = noauth
        self.lan_only = lan_only

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
        if self.noauth:
            ssh_tunnel = SSHTunnel(self.local_port)
            if ssh_tunnel.start():
                self.active_tunnel = ssh_tunnel
                self.public_url = ssh_tunnel.public_url
                success = True
            else:
                print("\n[!] No-auth SSH tunnel failed. Falling back to ngrok...")

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


# ─────────────────────────────────────────────────────────
#  QR CODE GENERATION  (preserved)
# ─────────────────────────────────────────────────────────
def generate_qr_code(primary_url, fallback_url=None):
    try:
        import qrcode

        qr = qrcode.QRCode(
            version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=2
        )
        qr.add_data(primary_url)
        qr.make(fit=True)
        print("\n" + "=" * 60)
        if fallback_url:
            print(
                f"  {CLR_G}{DOT} {CLR_Y}{DOT} {CLR_R}{DOT} {CLR_B}{DOT}{CLR_RST}  qrtunnel - Smart mode enabled"
            )
            print("=" * 60)
            qr.print_ascii(invert=True)
            print("=" * 60)
            print(f"{INFO} Internet link: {primary_url}")
            print(f"{OK} Fast local link: {fallback_url}")
            print("(Auto-detects and switches to High Speed if on same Wi-Fi)")
        else:
            print("SCAN THIS QR CODE TO ACCESS THE FILES:")
            print("=" * 60)
            qr.print_ascii(invert=True)
            print("=" * 60)
            print(f"\n{INFO} URL: {primary_url}")
        if Config.OTP:
            print("-" * 60)
            print(f"🔒 LAN PASSWORD: {CLR_G}{Config.OTP}{CLR_RST}")
            print("-" * 60)
        print("=" * 60 + "\n")
    except ImportError:
        print("\n" + "=" * 60)
        print(f"{WRN} QR code library not installed")
        print("Install with: pip install qrcode")
        print("=" * 60)
        print(f"{OK} Link: {primary_url}")
        if fallback_url:
            print(f"{INFO} Fallback: {fallback_url}")
        print("=" * 60 + "\n")


# ─────────────────────────────────────────────────────────
#  TUI  –  the interactive arrow-key interface
# ─────────────────────────────────────────────────────────
# Screen IDs
SCR_MAIN = 0  # SEND / RECEIVE / EXIT
SCR_FILES = 1  # file-picker (SEND only)
SCR_MODE = 2  # tunnel-mode picker
SCR_PORT = 3  # port picker
SCR_CONFIRM = 4  # final review before launch


def _top_bar():
    """Return the shared top banner lines."""
    return [
        f"{CLR_DIM}{'─' * W}{CLR_RST}",
        f"  {CLR_B}{CLR_BLD}qrtunnel{CLR_RST}  {CLR_DIM}v{__version__}  •  cross-platform file transfer{CLR_RST}",
        f"{CLR_DIM}{'─' * W}{CLR_RST}",
    ]


def _nav_hint(back=True, fwd=True, search=False):
    """Small navigation hint line."""
    parts = []
    if back:
        parts.append(f"{CLR_DIM}← back{CLR_RST}")
    if fwd:
        parts.append(f"{CLR_DIM}→ proceed{CLR_RST}")
    parts.append(f"{CLR_DIM}↑↓ move{CLR_RST}")
    if search:
        parts.append(f"{CLR_C}/ search{CLR_RST}")
    parts.append(f"{CLR_R}q quit{CLR_RST}")
    return "  " + "   ".join(parts)


# ── Screen 0 – Main ──────────────────────────────────────
def draw_main(cursor):
    items = ["SEND", "RECEIVE", "EXIT"]
    icons = [CLR_G, CLR_B, CLR_R]
    lines = _top_bar()
    lines.append("")
    for i, (label, clr) in enumerate(zip(items, icons)):
        if i == cursor:
            lines.append(f"  {clr}{CLR_BLD}▸ {label}{CLR_RST}")
        else:
            lines.append(f"  {CLR_DIM}  {label}{CLR_RST}")
    lines.append("")
    lines.append(_nav_hint(back=False, fwd=True))
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines


# ── Screen 1 – File Picker ────────────────────────────────
def _list_dir(path):
    """Return sorted (dirs first, then files) entries of *path*."""
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return [], []
    dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
    files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
    return dirs, files


def draw_files(cursor, cwd, selected_files, scroll_offset, search_query="", is_searching=False):
    dirs, files = _list_dir(cwd)

    # Filter
    if search_query:
        q = search_query.lower()
        dirs = [d for d in dirs if q in d.lower()]
        files = [f for f in files if q in f.lower()]

    # build item list: [.. ] then dirs then files
    items = []  # (display_str,  full_path, kind)
    if cwd != os.path.abspath(os.sep) and not search_query:  # Hide '..' during search
        items.append(("  ..", None, "back"))
    for d in dirs:
        items.append((f"  {d}/", os.path.join(cwd, d), "dir"))
    for f in files:
        size = format_size(os.path.getsize(os.path.join(cwd, f)))
        items.append((f"  {f}", os.path.join(cwd, f), "file"))

    # viewport
    max_visible = 18
    if cursor >= len(items):
        cursor = len(items) - 1
    if cursor < 0:
        cursor = 0

    # Auto-scroll
    if cursor < scroll_offset:
        scroll_offset = cursor
    elif cursor >= scroll_offset + max_visible:
        scroll_offset = cursor - max_visible + 1

    visible_start = scroll_offset
    visible_end = min(len(items), scroll_offset + max_visible)

    lines = _top_bar()
    lines.append(f"  {CLR_M}{CLR_BLD}Select files to send{CLR_RST}")
    lines.append(f"  {CLR_DIM}{cwd}{CLR_RST}")

    # Search Bar
    if is_searching or search_query:
        prefix = "/" if is_searching else "Search:"
        cursor_char = "█" if is_searching else ""
        lines.append(f"  {CLR_Y}{prefix} {search_query}{cursor_char}{CLR_RST}")
    else:
        lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")

    if not items and search_query:
        lines.append(f"  {CLR_DIM}(No matches found){CLR_RST}")

    for idx in range(visible_start, visible_end):
        label, full, kind = items[idx]
        is_cursor = idx == cursor

        if kind == "back":
            txt = f"{CLR_Y}..{CLR_RST}"
            if is_cursor:
                lines.append(f"  {CLR_Y}{CLR_BLD}▸ {txt}{CLR_RST}")
            else:
                lines.append(f"    {txt}")
        elif kind == "dir":
            dname = os.path.basename(full)
            if is_cursor:
                lines.append(f"  {CLR_C}{CLR_BLD}▸ {dname}/{CLR_RST}")
            else:
                lines.append(f"  {CLR_C}  {dname}/{CLR_RST}")
        else:  # file
            fname = os.path.basename(full)
            size = format_size(os.path.getsize(full))
            is_sel = full in selected_files

            # Selection marker
            mark = f"{CLR_G}[x]{CLR_RST}" if is_sel else f"{CLR_DIM}[ ]{CLR_RST}"

            if is_cursor:
                lines.append(
                    f"  {CLR_W}{CLR_BLD}▸ {mark} {fname}{CLR_RST}  {CLR_DIM}{size}{CLR_RST}"
                )
            else:
                lines.append(f"    {mark} {fname}  {CLR_DIM}{size}{CLR_RST}")

    # scroll indicator
    if len(items) > max_visible:
        lines.append(f"  {CLR_DIM}({visible_start + 1}–{visible_end} / {len(items)}){CLR_RST}")

    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")

    # selected summary
    if selected_files:
        total = sum(os.path.getsize(f) for f in selected_files)
        lines.append(
            f"  {CLR_G}Selected: {len(selected_files)} file(s)  •  {format_size(total)}{CLR_RST}"
        )
    else:
        lines.append(f"  {CLR_DIM}No files selected{CLR_RST}")

    lines.append(_nav_hint(back=True, fwd=True, search=True))
    lines.append(f"  {CLR_DIM}Space/Enter = toggle   Enter on dir = open{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines, items


# ── Screen 2 – Mode ───────────────────────────────────────
MODE_OPTIONS = [
    ("Smart", "LAN + Public Tunnel  (auto high-speed)"),
    ("LAN", "Local network only   (fastest, same Wi-Fi)"),
    ("SSH", "localhost.run        (no sign-up)"),
    ("Ngrok", "ngrok tunnel         (requires account)"),
]


def draw_mode(cursor):
    lines = _top_bar()
    lines.append(f"  {CLR_C}{CLR_BLD}Select tunnel mode{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    for i, (name, desc) in enumerate(MODE_OPTIONS):
        if i == cursor:
            lines.append(f"  {CLR_M}{CLR_BLD}▸ {name:<8}{CLR_RST}  {desc}")
        else:
            lines.append(f"  {CLR_DIM}  {name:<8}  {desc}{CLR_RST}")
    lines.append("")
    lines.append(_nav_hint(back=True, fwd=True))
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines


# ── Screen 3 – Port ───────────────────────────────────────
PORT_OPTIONS = [
    ("Random", "Auto-pick a safe port (20 000–60 000)"),
    ("Custom", "Type your own port number"),
]


def draw_port(cursor, custom_port_str):
    lines = _top_bar()
    lines.append(f"  {CLR_Y}{CLR_BLD}Select port{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    for i, (name, desc) in enumerate(PORT_OPTIONS):
        if i == cursor:
            lines.append(f"  {CLR_Y}{CLR_BLD}▸ {name:<10}{CLR_RST}  {desc}")
        else:
            lines.append(f"  {CLR_DIM}  {name:<10}  {desc}{CLR_RST}")
    if cursor == 1:  # custom selected – show live input
        lines.append("")
        lines.append(f"  Port number:  {CLR_W}{CLR_BLD}{custom_port_str or '_'}{CLR_RST}")
    lines.append("")
    lines.append(_nav_hint(back=True, fwd=True))
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines


# ── Screen 4 – Confirm ────────────────────────────────────
def draw_confirm(mode_name, is_send, selected_files, port_val):
    lines = _top_bar()
    lines.append(f"  {CLR_G}{CLR_BLD}Ready to launch{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")

    action = "SEND" if is_send else "RECEIVE"
    lines.append(f"    Direction  →  {CLR_W}{action}{CLR_RST}")
    lines.append(f"    Tunnel     →  {CLR_W}{mode_name}{CLR_RST}")
    lines.append(f"    Port       →  {CLR_W}{port_val}{CLR_RST}")

    if is_send and selected_files:
        lines.append("")
        lines.append(f"    {CLR_DIM}Files:{CLR_RST}")
        total = 0
        for fp in selected_files:
            sz = os.path.getsize(fp)
            total += sz
            lines.append(f"      {CLR_DIM}{os.path.basename(fp)}  ({format_size(sz)}){CLR_RST}")
        lines.append(f"      {CLR_G}Total: {format_size(total)}{CLR_RST}")
    elif not is_send:
        lines.append(f"    {CLR_DIM}Receive dir  →  {os.getcwd()}{CLR_RST}")

    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    lines.append(f"  {CLR_G}{CLR_BLD}▸ LAUNCH{CLR_RST}    (Enter)")
    lines.append(f"  {CLR_DIM}  ← Back{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines


# ── RENDER helper ─────────────────────────────────────────
def render(lines):
    """Clear screen and print all lines."""
    sys.stdout.write(CLEAR)
    # In raw mode on Unix, we need explicit carriage returns.
    sep = "\r\n" if platform.system() != "Windows" else "\n"
    sys.stdout.write(sep.join(lines))
    sys.stdout.write(sep)
    sys.stdout.flush()


class UnixRawMode:
    """Context manager to enable raw mode on Unix (no-op on Windows)."""

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.old_settings = None

    def __enter__(self):
        if platform.system() != "Windows":
            import termios
            import tty

            try:
                self.old_settings = termios.tcgetattr(self.fd)
                # tty.setraw disables all processing (input and output)
                tty.setraw(self.fd, termios.TCSADRAIN)
            except Exception:
                pass  # e.g. not a TTY
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.old_settings:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)


# ── MAIN TUI LOOP ─────────────────────────────────────────
def run_tui():
    """Drive the multi-screen TUI.  Returns (is_send, file_paths, mode, port) or None on exit."""
    # ── state ──
    screen = SCR_MAIN
    cursor = 0
    cwd = os.getcwd()
    selected_files = []
    mode_cursor = 0
    port_cursor = 0
    custom_port = ""  # live typed string
    custom_port_editing = False  # are we typing?
    file_scroll = 0

    # Search state
    search_query = ""
    is_searching = False

    # for RECEIVE we skip the file-picker so we remember where to resume
    screen_is_send = True
    # history stack: each push records (screen_id, cursor) so ← pops cleanly
    history = []

    def push(scr, cur):
        history.append((scr, cur))

    sys.stdout.write(HIDE_CURSOR)
    # Enable global raw mode for the duration of the TUI
    with UnixRawMode():
        try:
            while True:
                # ── DRAW ──
                if screen == SCR_MAIN:
                    render(draw_main(cursor))

                elif screen == SCR_FILES:
                    # Pass search state to draw_files
                    lines, items = draw_files(
                        cursor, cwd, selected_files, file_scroll, search_query, is_searching
                    )
                    render(lines)

                elif screen == SCR_MODE:
                    render(draw_mode(mode_cursor))

                elif screen == SCR_PORT:
                    render(draw_port(port_cursor, custom_port if port_cursor == 1 else None))

                elif screen == SCR_CONFIRM:
                    mode_name = MODE_OPTIONS[mode_cursor][0]
                    port_val = custom_port if (port_cursor == 1 and custom_port) else "Random"
                    render(draw_confirm(mode_name, screen_is_send, selected_files, port_val))

                # ── READ KEY ──
                key = read_key()
                if key is None:
                    continue
                if key == "CTRL_C":
                    return None

                # Global Quit (only if not typing text)
                if key == "q" and not custom_port_editing and not is_searching:
                    return None

                # ── HANDLE PER-SCREEN ──
                if screen == SCR_MAIN:
                    if key == "DOWN":
                        cursor = min(cursor + 1, 2)
                    elif key == "UP":
                        cursor = max(cursor - 1, 0)
                    elif key in ("ENTER", "RIGHT"):
                        if cursor == 0:  # SEND
                            screen_is_send = True
                            push(SCR_MAIN, 0)
                            screen = SCR_FILES
                            cursor = 0
                            file_scroll = 0
                            cwd = os.getcwd()
                        elif cursor == 1:  # RECEIVE
                            screen_is_send = False
                            push(SCR_MAIN, 1)
                            screen = SCR_MODE
                            mode_cursor = 0
                        else:  # EXIT
                            return None

                elif screen == SCR_FILES:
                    # Search Input Handling
                    if is_searching:
                        if key == "ESC":
                            is_searching = False
                            search_query = ""
                        elif key == "ENTER":
                            is_searching = False
                        elif key == "BACKSPACE":
                            search_query = search_query[:-1]
                        elif len(key) == 1 and key.isprintable():
                            search_query += key
                            # Reset cursor/scroll on typing
                            cursor = 0
                            file_scroll = 0
                        continue

                    # Normal Navigation
                    _, items = draw_files(
                        cursor, cwd, selected_files, file_scroll, search_query, is_searching
                    )
                    total_items = len(items)

                    if key == "/":  # Enter Search Mode
                        is_searching = True
                        continue

                    if key == "DOWN":
                        if cursor < total_items - 1:
                            cursor += 1
                            if cursor >= file_scroll + 18:
                                file_scroll += 1
                    elif key == "UP":
                        if cursor > 0:
                            cursor -= 1
                            if cursor < file_scroll:
                                file_scroll -= 1
                    elif key == "LEFT":  # ← back to main
                        if search_query:  # Clear search first if active
                            search_query = ""
                            cursor = 0
                            file_scroll = 0
                        else:
                            scr, cur = history.pop() if history else (SCR_MAIN, 0)
                            screen = scr
                            cursor = cur
                    elif key == "SPACE":  # toggle file
                        if cursor < total_items:
                            _, full, kind = items[cursor]
                            if kind == "file":
                                if full in selected_files:
                                    selected_files.remove(full)
                                else:
                                    selected_files.append(full)
                    elif key == "ENTER":
                        if cursor < total_items:
                            _, full, kind = items[cursor]
                            if kind == "back":
                                cwd = os.path.dirname(cwd)
                                cursor = 0
                                file_scroll = 0
                                search_query = ""  # reset search on dir change
                            elif kind == "dir":
                                cwd = full
                                cursor = 0
                                file_scroll = 0
                                search_query = ""  # reset search on dir change
                            else:  # file – toggle selection
                                if full in selected_files:
                                    selected_files.remove(full)
                                else:
                                    selected_files.append(full)
                    elif key == "RIGHT":  # → advance to MODE (only if files selected)
                        if selected_files:
                            push(SCR_FILES, cursor)
                            screen = SCR_MODE
                            mode_cursor = 0

                elif screen == SCR_MODE:
                    if key == "DOWN":
                        mode_cursor = min(mode_cursor + 1, len(MODE_OPTIONS) - 1)
                    elif key == "UP":
                        mode_cursor = max(mode_cursor - 1, 0)
                    elif key == "LEFT":
                        scr, cur = history.pop() if history else (SCR_MAIN, 0)
                        screen = scr
                        cursor = cur
                    elif key in ("ENTER", "RIGHT"):
                        push(SCR_MODE, mode_cursor)
                        screen = SCR_PORT
                        port_cursor = 0
                        custom_port = ""

                elif screen == SCR_PORT:
                    if custom_port_editing:
                        # capture typed digits
                        if key == "BACKSPACE":
                            custom_port = custom_port[:-1]
                        elif key in ("ENTER", "RIGHT"):
                            # validate
                            if custom_port.isdigit() and 1 <= int(custom_port) <= 65535:
                                custom_port_editing = False
                                push(SCR_PORT, port_cursor)
                                screen = SCR_CONFIRM
                            # else stay – let user fix
                        elif key == "LEFT":
                            custom_port_editing = False  # cancel typing, stay on screen
                        elif key and key.isdigit() and len(custom_port) < 5:
                            custom_port += key
                        continue  # skip the normal port-screen nav below

                    if key == "DOWN":
                        port_cursor = min(port_cursor + 1, 1)
                    elif key == "UP":
                        port_cursor = max(port_cursor - 1, 0)
                    elif key == "LEFT":
                        scr, cur = history.pop() if history else (SCR_MAIN, 0)
                        screen = scr
                        cursor = cur if scr != SCR_MODE else mode_cursor
                        mode_cursor = cur if scr == SCR_MODE else mode_cursor
                    elif key in ("ENTER", "RIGHT"):
                        if port_cursor == 0:  # random – go straight to confirm
                            custom_port = ""
                            push(SCR_PORT, port_cursor)
                            screen = SCR_CONFIRM
                        else:  # custom – start typing
                            custom_port = ""
                            custom_port_editing = True

                elif screen == SCR_CONFIRM:
                    if key in ("ENTER",):  # LAUNCH
                        break  # exit loop → caller launches
                    elif key in ("LEFT",):
                        scr, cur = history.pop() if history else (SCR_MAIN, 0)
                        screen = scr
                        # restore the right cursor variable
                        if scr == SCR_PORT:
                            port_cursor = cur
                        elif scr == SCR_MODE:
                            mode_cursor = cur
                        elif scr == SCR_FILES:
                            cursor = cur
                        else:
                            cursor = cur

        finally:
            sys.stdout.write(SHOW_CURSOR)
            sys.stdout.flush()

    # ── resolve final values ──
    mode_name = MODE_OPTIONS[mode_cursor][0]

    if port_cursor == 1 and custom_port.isdigit():
        final_port = int(custom_port)
    else:
        final_port = random.randint(20000, 60000)

    return screen_is_send, selected_files, mode_name, final_port


# ─────────────────────────────────────────────────────────
#  POST-TUI LAUNCH  (server + QR)
# ─────────────────────────────────────────────────────────
def launch_server(is_send, file_paths, mode_name, port):
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
    print(f"Security: LAN Access Code -> [{CLR_G}{Config.OTP}{CLR_RST}]")
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

    # ── start tunnel ──
    if not tunnel_manager.start():
        server.shutdown()
        sys.exit(1)

    # ── QR code ──
    if tunnel_manager.lan_url and tunnel_manager.public_url:
        generate_qr_code(tunnel_manager.public_url, tunnel_manager.lan_url)
    elif tunnel_manager.public_url:
        generate_qr_code(tunnel_manager.public_url)
    else:
        generate_qr_code(tunnel_manager.lan_url)

    print("[*] Server is running.  Press 'q' or Ctrl+C to stop.\n")

    # ── wait loop ──
    try:
        while True:
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
        tunnel_manager.stop()
        server.shutdown()
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

    return args, port


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
        file_paths = [os.path.abspath(f) for f in args.files]
        for f in file_paths:
            if not os.path.exists(f):
                print(f"{ERR} File not found: {f}")
                sys.exit(1)
    else:
        # Receive mode
        target_dir = os.path.abspath(args.dest)
        if not os.path.isdir(target_dir):
            print(f"{ERR} Destination is not a directory: {target_dir}")
            sys.exit(1)
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

    launch_server(is_send, file_paths, mode_name, cli_port)


if __name__ == "__main__":
    main()
