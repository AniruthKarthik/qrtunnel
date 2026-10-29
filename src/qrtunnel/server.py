"""HTTP handlers for file download and upload."""

import http.cookies
import io
import mimetypes
import os
import platform
import re
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse

from streaming_form_data import StreamingFormDataParser
from streaming_form_data.targets import FileTarget

from .config import Config
from .constants import ERR, INFO, OK, WRN
from .history import log_transfer
from .streams import LimitedStream
from .utils import (
    format_progress,
    format_size,
    is_same_lan,
    is_same_network,
    sha256_file,
)

_stdout_lock = threading.Lock()


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

    def print_progress(self, label, transferred, total, force=False, last_update=0):
        now = time.monotonic()
        if not force and now - last_update < 0.25:
            return last_update
        with _stdout_lock:
            # \033[K clears from cursor position to the end of the line
            print(f"\r\033[K[*] {label}: {format_progress(transferred, total)}", end="", flush=True)
        return now

    # ── auth ──
    def check_auth(self):
        if self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        if self.path == "/ping" or self.path.startswith("/ping?"):
            return True
        # Allow token in query parameter for seamless transition from Tunnel to LAN
        try:
            parsed = urlparse(self.path)
            from urllib.parse import parse_qs

            params = parse_qs(parsed.query)
            token = params.get("auth", [None])[0]
            if token and token in self.authorized_sessions:
                return True
        except Exception:
            pass
        cookie_header = self.headers.get("Cookie")
        if cookie_header:
            try:
                cookies = http.cookies.SimpleCookie(cookie_header)
                if "session" in cookies:
                    if cookies["session"].value in self.authorized_sessions:
                        return True
            except Exception:
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

    # ── client network detection ──
    def get_real_client_ip(self):
        cf_ip = self.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        x_real = self.headers.get("X-Real-IP")
        if x_real:
            return x_real.strip()
        return self.client_address[0]

    def is_tunnel_request(self):
        return bool(
            self.headers.get("CF-Connecting-IP")
            or self.headers.get("X-Forwarded-For")
            or self.headers.get("X-Real-IP")
        )

    def is_request_from_same_lan(self):
        lan_ip = str(self.server_lan_ip) if self.server_lan_ip else ""
        if not lan_ip or lan_ip in ("None", "127.0.0.1"):
            return False
        real_ip = self.get_real_client_ip()
        return is_same_network(real_ip, lan_ip)

    # ── logging ──
    def log_message(self, format, *args):
        client_ip = self.client_address[0]
        real_ip = self.get_real_client_ip()

        if self.is_tunnel_request():
            if self.is_request_from_same_lan():
                conn_type = f"{OK} Smart LAN (via Tunnel)"
            else:
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
                conn_type = f"{INFO} Remote"
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
                if self.is_tunnel_request() and self.is_request_from_same_lan():
                    lan_ip = str(self.server_lan_ip) if self.server_lan_ip else ""
                    if lan_ip and lan_ip not in ("None", "127.0.0.1"):
                        token = str(uuid.uuid4())
                        self.authorized_sessions.add(token)
                        delim = "&" if "?" in self.path else "?"
                        lan_url = f"http://{lan_ip}:{Config.LOCAL_PORT}{self.path}{delim}auth={token}"
                        self.send_response(302)
                        self.send_header("Location", lan_url)
                        self.end_headers()
                        return
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

    def _send_auth_cookie_if_needed(self):
        try:
            parsed = urlparse(self.path)
            from urllib.parse import parse_qs

            token = parse_qs(parsed.query).get("auth", [None])[0]
            if token and token in self.authorized_sessions:
                self.send_header(
                    "Set-Cookie", f"session={token}; Path=/; HttpOnly; Max-Age=86400"
                )
        except Exception:
            pass

    # ── smart redirect JS ──
    def get_smart_redirect_js(self):
        lan_ip = str(self.server_lan_ip) if self.server_lan_ip else ""
        if not lan_ip or lan_ip in ("None", "127.0.0.1"):
            return ""

        # Pre-authenticate handover session token if auth is enabled
        token = str(uuid.uuid4())
        self.authorized_sessions.add(token)
        lan_target = f"http://{lan_ip}:{Config.LOCAL_PORT}{self.path}"
        delim = "&" if "?" in lan_target else "?"
        lan_url = f"{lan_target}{delim}auth={token}"

        is_same_net = self.is_request_from_same_lan()
        if is_same_net:
            # Client verified on same Wi-Fi / local network: unhide switch link and auto-redirect
            return f"""
    <script>
        (function() {{
            var lanIp = "{lan_ip}";
            var lanUrl = "{lan_url}";
            if (window.location.hostname !== lanIp) {{
                var discoveryDiv = document.getElementById('lan-discovery');
                var lanBtn = document.getElementById('lan-btn');
                if (discoveryDiv && lanBtn) {{
                    discoveryDiv.style.display = 'block';
                    lanBtn.href = lanUrl;
                }}
                setTimeout(function() {{
                    window.location.href = lanUrl;
                }}, 250);
            }}
        }})();
    </script>"""

        return f"""
    <script>
        (function() {{
            var lanIp = "{lan_ip}";
            var lanPort = {Config.LOCAL_PORT};
            var lanUrl = "{lan_url}";
            if (window.location.hostname !== lanIp) {{
                var discoveryDiv = document.getElementById('lan-discovery');
                var lanBtn = document.getElementById('lan-btn');
                var img = new Image();
                img.onload = function() {{
                    if (discoveryDiv && lanBtn) {{
                        discoveryDiv.style.display = 'block';
                        lanBtn.href = lanUrl;
                    }}
                    setTimeout(function() {{
                        window.location.href = lanUrl;
                    }}, 100);
                }};
                img.src = "http://" + lanIp + ":" + lanPort + "/ping?t=" + Date.now();
            }}
        }})();
    </script>"""

    # ── upload handler ──
    def handle_upload(self):
        temp_path = None
        try:
            content_length_str = self.headers.get("Content-Length")
            if not content_length_str:
                self.send_error(411, "Length Required")
                return
            try:
                content_length = int(content_length_str)
            except ValueError:
                self.send_error(400, "Invalid Content-Length")
                return

            stream = LimitedStream(self.rfile, content_length)
            parser = StreamingFormDataParser(headers=self.headers)
            temp_filename = f"upload_{uuid.uuid4().hex}.tmp"
            temp_path = Path.cwd() / temp_filename
            file_target = FileTarget(str(temp_path))
            parser.register("file", file_target)
            chunk_size = 65536
            received = 0
            last_update = 0
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                received += len(chunk)
                parser.data_received(chunk)
                last_update = self.print_progress(
                    "Upload", received, content_length, last_update=last_update
                )
            self.print_progress("Upload", received, content_length, force=True)
            print()
            if not getattr(file_target, "multipart_filename", None):
                if temp_path.exists():
                    temp_path.unlink()
                self.send_error(400, "File not found in form data")
                return
            sanitized_filename = os.path.basename(unquote(file_target.multipart_filename))
            if not sanitized_filename:
                if temp_path.exists():
                    temp_path.unlink()
                self.send_error(400, "Invalid filename")
                return

            # Avoid silent overwrite by deduplicating filename
            base_stem = Path(sanitized_filename).stem
            base_ext = Path(sanitized_filename).suffix
            saved_filename = sanitized_filename
            counter = 1
            final_path = Path.cwd() / saved_filename
            while final_path.exists():
                saved_filename = f"{base_stem} ({counter}){base_ext}"
                final_path = Path.cwd() / saved_filename
                counter += 1

            os.rename(temp_path, final_path)
            print(f"{OK} File '{saved_filename}' received and saved to {final_path}")
            print(f"{OK} SHA256: {sha256_file(final_path)}")
            log_transfer(
                saved_filename,
                os.path.getsize(final_path),
                self.client_address[0],
                "receive",
            )
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            success_html = self.get_upload_success_page(saved_filename)
            self.send_header("Content-Length", str(len(success_html)))
            self._send_auth_cookie_if_needed()
            self.end_headers()
            self.wfile.write(success_html.encode())
            self.close_connection = True
        except Exception as e:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
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
.progress-container {{ display:none; margin-top:6px; }}
.progress-bar-bg {{ background:#0f0f1a; border-radius:6px; height:12px; overflow:hidden; border:1px solid #2a3a5e; }}
.progress-bar-fill {{ background:linear-gradient(90deg, #4361ee, #4cc9f0); height:100%; width:0%; transition:width 0.15s ease; }}
.progress-info {{ display:flex; justify-content:space-between; margin-top:8px; font-size:12px; color:#aaa; font-family:'SF Mono','Consolas',monospace; }}
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
<div id="progress-container" class="progress-container">
<div class="progress-bar-bg"><div id="progress-bar" class="progress-bar-fill"></div></div>
<div class="progress-info">
<span id="progress-pct">0%</span>
<span id="progress-speed">0 B/s</span>
<span id="progress-stats">0 B / 0 B</span>
</div>
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
const uploadForm = document.getElementById('upload-form');
const progressContainer = document.getElementById('progress-container');
const progressBar = document.getElementById('progress-bar');
const progressPct = document.getElementById('progress-pct');
const progressSpeed = document.getElementById('progress-speed');
const progressStats = document.getElementById('progress-stats');

function formatBytes(bytes) {{
    if (bytes < 1024) return bytes + ' B';
    var kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    var mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + ' MB';
    var gb = mb / 1024;
    return gb.toFixed(1) + ' GB';
}}

fileInput.addEventListener('change', () => {{
    if (fileInput.files.length > 0) {{
        fileNameDisplay.textContent = 'Selected: ' + fileInput.files[0].name + ' (' + formatBytes(fileInput.files[0].size) + ')';
        submitButton.classList.add('enabled');
    }} else {{
        fileNameDisplay.textContent = '';
        submitButton.classList.remove('enabled');
    }}
}});

uploadForm.addEventListener('submit', (e) => {{
    if (!fileInput.files.length) return;
    e.preventDefault();
    submitButton.classList.remove('enabled');
    submitButton.style.opacity = '0.5';
    submitButton.style.pointerEvents = 'none';
    submitButton.textContent = 'Uploading...';
    progressContainer.style.display = 'block';

    var file = fileInput.files[0];
    var formData = new FormData();
    formData.append('file', file);

    var xhr = new XMLHttpRequest();
    var lastLoaded = 0;
    var lastTime = Date.now();

    xhr.upload.onprogress = (ev) => {{
        if (ev.lengthComputable) {{
            var now = Date.now();
            var pct = ((ev.loaded / ev.total) * 100).toFixed(1);
            progressBar.style.width = pct + '%';
            progressPct.textContent = pct + '%';
            progressStats.textContent = formatBytes(ev.loaded) + ' / ' + formatBytes(ev.total);

            var elapsedSec = (now - lastTime) / 1000;
            if (elapsedSec >= 0.4) {{
                var speed = (ev.loaded - lastLoaded) / elapsedSec;
                progressSpeed.textContent = formatBytes(speed) + '/s';
                lastLoaded = ev.loaded;
                lastTime = now;
            }}

            if (ev.loaded >= ev.total) {{
                submitButton.textContent = 'Processing on server...';
            }}
        }}
    }};

    xhr.onload = () => {{
        if (xhr.status === 200) {{
            document.open();
            document.write(xhr.responseText);
            document.close();
        }} else {{
            alert('Upload failed: ' + xhr.statusText);
            submitButton.classList.add('enabled');
            submitButton.style.opacity = '1';
            submitButton.style.pointerEvents = 'auto';
            submitButton.textContent = 'Upload';
        }}
    }};

    xhr.onerror = () => {{
        alert('Network error occurred during upload.');
        submitButton.classList.add('enabled');
        submitButton.style.opacity = '1';
        submitButton.style.pointerEvents = 'auto';
        submitButton.textContent = 'Upload';
    }};

    xhr.open('POST', '/upload', true);
    xhr.send(formData);
}});
</script>
{self.get_smart_redirect_js()}
</body></html>"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", len(html.encode()))
        self._send_auth_cookie_if_needed()
        self.end_headers()
        self.wfile.write(html.encode())

    # ── download page ──
    def send_download_page(self):
        file_list_html = ""
        basenames = [os.path.basename(fp) for fp in self.file_paths]
        has_duplicates = len(basenames) != len(set(basenames))
        for idx, fp in enumerate(self.file_paths):
            fn = os.path.basename(fp)
            href_path = f"/download/{idx}/{fn}" if has_duplicates else f"/download/{fn}"
            display_name = (
                f"{os.path.basename(os.path.dirname(fp))}/{fn}" if has_duplicates else fn
            )
            size_label = format_size(os.path.getsize(fp)) if os.path.isfile(fp) else "folder"
            file_list_html += (
                f'<li><a href="{href_path}" class="file-link">'
                f'<span>{display_name}</span><span class="file-size">{size_label}</span></a></li>'
            )
        zip_link_html = ""
        if len(self.file_paths) > 1 or any(os.path.isdir(fp) for fp in self.file_paths):
            zip_link_html = '<a href="/download/all.zip" class="zip-link">Download all as ZIP</a>'
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
.file-link {{ display:flex; justify-content:space-between; align-items:center; padding:12px 16px; font-size:14px;
              font-family:'SF Mono','Consolas',monospace; color:#ccc;
              text-decoration:none; transition:background-color 0.2s; }}
.file-link:hover {{ background-color:#2a3a5e; }}
.file-size {{ font-size:12px; color:#888; margin-left:12px; }}
.zip-link {{ display:block; margin-top:16px; padding:12px 16px; background:#4361ee; color:#fff;
             border-radius:6px; text-decoration:none; text-align:center; font-size:14px; }}
.zip-link:hover {{ background:#3a56d4; }}
.footer {{ text-align:center; margin-top:24px; font-size:12px; color:#555; }}
</style></head><body>
<div class="container">
<div class="header"><h1>Files Ready</h1><p class="subtitle">Click a file to download</p></div>
<div class="file-section">
<p class="file-section-title">Files ({len(self.file_paths)})</p>
<ul class="file-list">{file_list_html}</ul>
{zip_link_html}
</div>
<div id="lan-discovery" style="margin-top:20px;text-align:center;display:none;">
<p style="font-size:13px;color:#4CAF50;margin-bottom:10px;">Same Wi-Fi detected!</p>
<a id="lan-btn" href="#" style="font-size:14px;color:#4361ee;text-decoration:none;border:1px solid #4361ee;padding:8px 16px;border-radius:4px;">Switch to High Speed</a>
</div>
<p class="footer">qrtunnel</p>
</div>
{self.get_smart_redirect_js()}
</body></html>"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", len(html.encode()))
        self._send_auth_cookie_if_needed()
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

    def build_zip_archive(self, file_paths=None):
        buffer = io.BytesIO()
        paths = file_paths if file_paths is not None else self.file_paths
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for fp in paths:
                path = Path(fp)
                if path.is_dir():
                    for child in path.rglob("*"):
                        if child.is_file():
                            archive.write(child, path.name / child.relative_to(path))
                elif path.is_file():
                    archive.write(path, path.name)
        return buffer.getvalue()

    def serve_directory_zip(self, dir_path):
        dir_name = os.path.basename(dir_path.rstrip(os.sep))
        try:
            data = self.build_zip_archive(file_paths=[dir_path])
            total_size = len(data)
            self.send_response(200)
            self.send_header("Content-type", "application/zip")
            self.send_header(
                "Content-Disposition", f'attachment; filename="{dir_name}.zip"'
            )
            self.send_header("Content-Length", str(total_size))
            self._send_auth_cookie_if_needed()
            self.end_headers()
            sent = 0
            chunk_size = 262144  # 256 KB
            last_update = 0
            while sent < total_size:
                chunk = data[sent : sent + chunk_size]
                self.wfile.write(chunk)
                sent += len(chunk)
                last_update = self.print_progress(
                    f"Download {dir_name}.zip", sent, total_size, last_update=last_update
                )
            self.print_progress(f"Download {dir_name}.zip", sent, total_size, force=True)
            print()
            print(f"{OK} Directory ZIP archive '{dir_name}.zip' served to {self.client_address[0]}")
            log_transfer(f"{dir_name}.zip", total_size, self.client_address[0], "send")
        except BrokenPipeError:
            print(f"\n{ERR} Client disconnected during ZIP transfer of '{dir_name}'")
        except Exception as e:
            print(f"{ERR} Error serving directory ZIP '{dir_name}': {e}")
            self.send_error(500, "Internal Server Error")

    def serve_zip_archive(self):
        try:
            data = self.build_zip_archive()
            total_size = len(data)
            self.send_response(200)
            self.send_header("Content-type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="qrtunnel-files.zip"')
            self.send_header("Content-Length", str(total_size))
            self._send_auth_cookie_if_needed()
            self.end_headers()
            sent = 0
            chunk_size = 262144  # 256 KB
            last_update = 0
            while sent < total_size:
                chunk = data[sent : sent + chunk_size]
                self.wfile.write(chunk)
                sent += len(chunk)
                last_update = self.print_progress(
                    "Download all.zip", sent, total_size, last_update=last_update
                )
            self.print_progress("Download all.zip", sent, total_size, force=True)
            print()
            print(f"{OK} ZIP archive served to {self.client_address[0]}")
            log_transfer("qrtunnel-files.zip", total_size, self.client_address[0], "send")
        except BrokenPipeError:
            print(f"\n{ERR} Client disconnected during ZIP transfer")
        except Exception as e:
            print(f"{ERR} Error serving ZIP archive: {e}")
            self.send_error(500, "Internal Server Error")

    def serve_single_file(self, filename):
        if filename == "all.zip":
            self.serve_zip_archive()
            return
        target_path = None
        if "/" in filename:
            parts = filename.split("/", 1)
            if parts[0].isdigit():
                idx = int(parts[0])
                if 0 <= idx < len(self.file_paths):
                    target_path = self.file_paths[idx]
        if not target_path:
            for fp in self.file_paths:
                if os.path.basename(fp) == filename:
                    target_path = fp
                    break
        if not target_path or not os.path.exists(target_path):
            self.send_error(404, "File Not Found")
            return
        if os.path.isdir(target_path):
            self.serve_directory_zip(target_path)
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
            mtype, _ = mimetypes.guess_type(target_path)
            content_type = mtype if mtype else "application/octet-stream"
            self.send_header("Content-type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(target_path)}"')
            self.send_header("Content-Length", str(content_length))
            self.send_header("Accept-Ranges", "bytes")
            self._send_auth_cookie_if_needed()
            self.end_headers()
            with open(target_path, "rb") as f:
                if start > 0:
                    f.seek(start)
                if platform.system() == "Linux" and hasattr(os, "sendfile"):
                    try:
                        sent = 0
                        last_update = 0
                        chunk_size = 262144  # 256 KB slice for smooth progress reporting
                        while sent < content_length:
                            to_send = min(chunk_size, content_length - sent)
                            n = os.sendfile(
                                self.connection.fileno(),
                                f.fileno(),
                                start + sent,
                                to_send,
                            )
                            if n == 0:
                                break
                            sent += n
                            last_update = self.print_progress(
                                f"Download {filename}",
                                start + sent,
                                file_size,
                                last_update=last_update,
                            )
                        self.print_progress(
                            f"Download {filename}", start + sent, file_size, force=True
                        )
                        print()
                    except BrokenPipeError:
                        print(f"\n{ERR} Client disconnected during transfer of '{filename}'")
                else:
                    try:
                        remaining = content_length
                        chunk_size = 262144  # 256 KB
                        sent = 0
                        last_update = 0
                        while remaining > 0:
                            chunk = f.read(min(chunk_size, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                            sent += len(chunk)
                            last_update = self.print_progress(
                                f"Download {filename}",
                                start + sent,
                                file_size,
                                last_update=last_update,
                            )
                        self.print_progress(
                            f"Download {filename}", start + sent, file_size, force=True
                        )
                        print()
                    except BrokenPipeError:
                        print(f"\n{ERR} Client disconnected during transfer of '{filename}'")
            if not range_req or (range_req and end == file_size - 1):
                print(f"{OK} File '{filename}' served to {self.client_address[0]}")
                print(f"{OK} SHA256: {sha256_file(target_path)}")
                log_transfer(filename, file_size, self.client_address[0], "send")
        except Exception as e:
            if not isinstance(e, BrokenPipeError) and "Broken pipe" not in str(e):
                print(f"{ERR} Error serving file '{filename}': {e}")
                if not self.wfile.closed:
                    try:
                        self.send_error(500, "Internal Server Error")
                    except Exception:
                        pass
