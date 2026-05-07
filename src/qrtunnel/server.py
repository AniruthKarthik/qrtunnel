"""HTTP handlers for file download and upload."""

import http.cookies
import os
import platform
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse

from streaming_form_data import StreamingFormDataParser
from streaming_form_data.targets import FileTarget

from .config import Config
from .constants import ERR, INFO, OK, WRN
from .streams import LimitedStream
from .utils import is_same_lan


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
                    except Exception:
                        pass


