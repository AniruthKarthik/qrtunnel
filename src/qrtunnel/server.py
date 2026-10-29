"""HTTP handlers for file download and upload."""

import http.cookies
import io
import json
import mimetypes
import os
import platform
import queue
import re
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, unquote, urlparse

from streaming_form_data import StreamingFormDataParser
from streaming_form_data.targets import BaseTarget

from .config import Config
from .constants import ERR, INFO, OK, WRN
from .history import log_transfer
from .qr import generate_qr_svg
from .streams import LimitedStream
from .sync import sender_sync
from .utils import (
    format_progress,
    format_size,
    get_lan_ip,
    is_same_lan,
    is_same_network,
    sha256_file,
)

_stdout_lock = threading.Lock()


class MultiFileTarget(BaseTarget):
    """StreamingFormData target that handles multiple uploaded files."""

    def __init__(self, upload_dir):
        super().__init__()
        self.upload_dir = Path(upload_dir)
        self.files = []
        self._current_fd = None
        self._current_tmp = None
        self._current_filename = None

    def on_start(self):
        self._current_filename = self.multipart_filename
        if self._current_filename and self._current_filename.strip():
            self._current_tmp = self.upload_dir / f"upload_{uuid.uuid4().hex}.tmp"
            self._current_fd = open(self._current_tmp, "wb")
        else:
            self._current_tmp = None
            self._current_fd = None

    def on_data_received(self, chunk: bytes):
        if self._current_fd:
            self._current_fd.write(chunk)

    def on_finish(self):
        if self._current_fd:
            self._current_fd.close()
            self._current_fd = None
            if self._current_filename and self._current_filename.strip():
                self.files.append((self._current_filename, self._current_tmp))
            elif self._current_tmp and self._current_tmp.exists():
                try:
                    self._current_tmp.unlink()
                except Exception:
                    pass

    def cleanup(self):
        if self._current_fd:
            try:
                self._current_fd.close()
            except Exception:
                pass
            self._current_fd = None
        for _, tmp_path in self.files:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
        if self._current_tmp and self._current_tmp.exists():
            try:
                self._current_tmp.unlink()
            except Exception:
                pass


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
        try:
            sender_sync.update_progress(label, transferred, total)
        except Exception:
            pass
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
                self.send_login_page(error="Incorrect 4-digit code")
        except Exception as e:
            print(f"{ERR} Auth error: {e}")
            self.send_error(500, "Internal Server Error")

    def send_login_page(self, error=None):
        error_html = f'<div class="error">{error}</div>' if error else ""
        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - Security Check</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:#f8fafc; color:#0f172a; min-height:100vh; display:flex; flex-direction:column;
       align-items:center; justify-content:center; padding:20px 16px; -webkit-font-smoothing:antialiased; }}
.container {{ background:#ffffff; border:1px solid #e2e8f0; border-radius:16px; padding:32px 24px;
             box-shadow:0 4px 6px -1px rgba(0,0,0,0.05),0 2px 4px -2px rgba(0,0,0,0.05);
             max-width:380px; width:100%; text-align:center; }}
.badge-icon {{ display:inline-flex; align-items:center; justify-content:center; width:48px; height:48px;
              border-radius:12px; background:#eff6ff; color:#2563eb; margin-bottom:14px; }}
h1 {{ font-size:20px; font-weight:700; color:#0f172a; margin-bottom:6px; letter-spacing:-0.3px; }}
.subtitle {{ font-size:14px; color:#64748b; margin-bottom:20px; line-height:1.4; }}
.error {{ color:#dc2626; font-size:13px; font-weight:500; margin-bottom:14px; background:#fef2f2;
         border:1px solid #fecaca; border-radius:8px; padding:8px 12px; }}
input {{ width:100%; padding:14px; margin-bottom:16px; background:#f8fafc; border:1.5px solid #cbd5e1;
        color:#0f172a; border-radius:10px; font-size:26px; font-weight:700; text-align:center;
        letter-spacing:6px; font-family:monospace; outline:none; transition:border-color 0.15s, box-shadow 0.15s; }}
input:focus {{ border-color:#2563eb; box-shadow:0 0 0 3px rgba(37,99,235,0.12); }}
button {{ width:100%; padding:14px 20px; background:#2563eb; color:#fff; border:none; border-radius:10px;
         font-size:15px; font-weight:600; cursor:pointer; transition:background 0.15s, transform 0.1s; }}
button:hover {{ background:#1d4ed8; }}
button:active {{ transform:scale(0.99); }}
.footer {{ text-align:center; margin-top:24px; font-size:12px; color:#94a3b8; font-weight:500; }}
</style></head><body>
<div class="container">
<div class="badge-icon">
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
</div>
<h1>Security Check</h1>
<p class="subtitle">Enter the 4-digit access code shown on the host computer.</p>
{error_html}
<form action="/login" method="post">
<input type="text" name="password" pattern="[0-9]*" inputmode="numeric"
       placeholder="0000" maxlength="4" required autofocus autocomplete="off">
<button type="submit">Verify Code</button>
</form>
<p class="footer">qrtunnel</p>
</div></body></html>"""
        self.send_response(200 if not error else 403)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(len(html.encode())))
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
        parsed_path = urlparse(self.path)
        is_local = self.client_address[0] in ("127.0.0.1", "::1")

        # Sender Web UI & API routes (local access)
        if is_local:
            if parsed_path.path in ("/sender", "/sender/", "/sender.html") or (
                parsed_path.path in ("/", "/index.html")
                and not self.file_paths
                and not self.upload_mode
            ):
                self.send_sender_page()
                return
            if parsed_path.path == "/api/sender/state":
                self.handle_sender_state()
                return
            if parsed_path.path == "/api/sender/events":
                self.handle_sender_events()
                return

        if not self.check_auth():
            self.send_login_page()
            return
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
        parsed_path = urlparse(self.path)
        is_local = self.client_address[0] in ("127.0.0.1", "::1")

        # Sender API routes (local access)
        if is_local:
            if parsed_path.path == "/api/sender/close":
                self.handle_sender_close()
                return
            if parsed_path.path == "/api/sender/heartbeat":
                self.handle_sender_heartbeat()
                return
            if parsed_path.path == "/api/sender/share":
                self.handle_sender_share()
                return
            if parsed_path.path == "/api/sender/stop":
                self.handle_sender_stop()
                return

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
                self.send_header("Set-Cookie", f"session={token}; Path=/; HttpOnly; Max-Age=86400")
        except Exception:
            pass

    # ── upload handler ──
    def handle_upload(self):
        target = None
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
            target = MultiFileTarget(Path.cwd())
            parser.register("file", target)
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

            if not target.files:
                target.cleanup()
                self.send_error(400, "No files found in form data")
                return

            saved_files = []
            for raw_filename, tmp_path in target.files:
                sanitized_filename = os.path.basename(unquote(raw_filename))
                if not sanitized_filename:
                    sanitized_filename = "uploaded_file"

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

                os.rename(tmp_path, final_path)
                file_size = os.path.getsize(final_path)
                saved_files.append((saved_filename, file_size))
                print(f"{OK} File '{saved_filename}' received and saved to {final_path}")
                print(f"{OK} SHA256: {sha256_file(final_path)}")
                log_transfer(
                    saved_filename,
                    file_size,
                    self.client_address[0],
                    "receive",
                )

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            success_html = self.get_upload_success_page(saved_files)
            self.send_header("Content-Length", str(len(success_html.encode())))
            self._send_auth_cookie_if_needed()
            self.end_headers()
            self.wfile.write(success_html.encode())
            self.close_connection = True
        except Exception as e:
            if target:
                target.cleanup()
            print(f"{ERR} Error during upload: {e}")
            self.send_error(500, "Internal Server Error")

    def get_upload_success_page(self, files):
        if isinstance(files, str):
            file_items = [(files, None)]
        elif isinstance(files, list):
            file_items = [
                (item[0], item[1]) if isinstance(item, (tuple, list)) else (str(item), None)
                for item in files
            ]
        else:
            file_items = [(str(files), None)]

        total_files = len(file_items)
        if total_files == 1:
            fn, sz = file_items[0]
            label = f"{fn} ({format_size(sz)})" if sz is not None else fn
            subtitle = "The file was successfully received on the host computer."
            content_html = f'<div class="file-badge">{label}</div>'
            btn_label = "Upload Another File"
        else:
            subtitle = f"{total_files} files were successfully received on the host computer."
            items_html = ""
            for fn, sz in file_items:
                sz_str = (
                    f' <span style="color:#64748b;font-weight:400;">({format_size(sz)})</span>'
                    if sz is not None
                    else ""
                )
                items_html += f'<li style="padding:10px 14px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center;font-size:13px;font-weight:600;color:#0f172a;word-break:break-all;"><span style="text-align:left;">✓ {fn}</span>{sz_str}</li>'
            content_html = f'<ul style="list-style:none;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc;margin:16px 0 24px;max-height:220px;overflow-y:auto;text-align:left;">{items_html}</ul>'
            btn_label = "Upload More Files"

        return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - Upload Complete</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:#f8fafc; color:#0f172a; min-height:100vh; display:flex; flex-direction:column;
       align-items:center; justify-content:center; padding:20px 16px; -webkit-font-smoothing:antialiased; }}
.container {{ background:#ffffff; border:1px solid #e2e8f0; border-radius:16px; padding:36px 24px;
             box-shadow:0 4px 6px -1px rgba(0,0,0,0.05),0 2px 4px -2px rgba(0,0,0,0.05);
             max-width:440px; width:100%; text-align:center; }}
.success-icon {{ display:inline-flex; align-items:center; justify-content:center; width:56px; height:56px;
                border-radius:50%; background:#dcfce7; color:#16a34a; margin-bottom:16px; }}
h1 {{ font-size:20px; font-weight:700; color:#0f172a; margin-bottom:6px; letter-spacing:-0.3px; }}
.subtitle {{ font-size:14px; color:#64748b; line-height:1.4; }}
.file-badge {{ display:inline-block; font-size:13px; font-weight:600; color:#0f172a; background:#f1f5f9;
              border:1px solid #e2e8f0; padding:8px 14px; border-radius:10px; margin:16px 0 24px;
              word-break:break-all; max-width:100%; }}
.button {{ display:flex; align-items:center; justify-content:center; width:100%; padding:14px 20px;
          background:#2563eb; color:#ffffff; border:none; border-radius:12px; font-size:15px;
          font-weight:600; text-decoration:none; cursor:pointer; transition:background 0.15s, transform 0.1s;
          box-shadow:0 1px 2px rgba(37,99,235,0.2); }}
.button:hover {{ background:#1d4ed8; }}
.button:active {{ transform:scale(0.99); }}
.footer {{ text-align:center; margin-top:24px; font-size:12px; color:#94a3b8; font-weight:500; }}
</style></head><body>
<div class="container">
<div class="success-icon">
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
</div>
<h1>Upload Complete</h1>
<p class="subtitle">{subtitle}</p>
{content_html}
<a href="/" class="button">{btn_label}</a>
<p class="footer">qrtunnel</p>
</div></body></html>"""

    # ── sender UI and API ──
    def send_sender_page(self):
        state = sender_sync.get_state()
        initial_state_json = json.dumps(state)
        html = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - Sender</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:#f8fafc; color:#0f172a; min-height:100vh; display:flex; flex-direction:column;
       align-items:center; justify-content:center; padding:20px 16px; -webkit-font-smoothing:antialiased; }
.container { background:#ffffff; border:1px solid #e2e8f0; border-radius:16px; padding:32px 24px;
             box-shadow:0 4px 6px -1px rgba(0,0,0,0.05),0 2px 4px -2px rgba(0,0,0,0.05);
             max-width:440px; width:100%; text-align:center; }
@media (max-width:480px) { .container { padding:24px 18px; border-radius:14px; } }
.header { text-align:center; margin-bottom:20px; }
.badge-icon { display:inline-flex; align-items:center; justify-content:center; width:48px; height:48px;
              border-radius:12px; background:#eff6ff; color:#2563eb; margin-bottom:12px; }
h1 { font-size:20px; font-weight:700; color:#0f172a; margin-bottom:4px; letter-spacing:-0.3px; }
.subtitle { font-size:14px; color:#64748b; font-weight:400; }

/* File Drop Area */
.file-drop-area { position:relative; border:2px dashed #cbd5e1; border-radius:14px; padding:28px 16px;
                  text-align:center; background:#f8fafc; cursor:pointer; transition:all 0.15s ease; margin-bottom:14px; }
.file-drop-area:hover, .file-drop-area.dragover { border-color:#2563eb; background:#eff6ff; }
#file-input { position:absolute; top:0; left:0; width:100%; height:100%; opacity:0; cursor:pointer; }
.drop-icon { display:inline-flex; align-items:center; justify-content:center; width:44px; height:44px;
             border-radius:10px; background:#fff; border:1px solid #e2e8f0; color:#2563eb;
             margin-bottom:10px; box-shadow:0 1px 3px rgba(0,0,0,0.05); }
.drop-text { font-size:14px; font-weight:600; color:#0f172a; margin-bottom:2px; }
.drop-hint { font-size:12px; color:#64748b; }

/* File Preview List */
.file-preview-area { margin-bottom:16px; text-align:left; }
.file-section-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
.file-section-title { font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:#94a3b8; }
.file-count-badge { font-size:11px; font-weight:600; color:#2563eb; background:#eff6ff; padding:2px 8px; border-radius:12px; }
.clear-btn { background:none; border:none; color:#ef4444; font-size:12px; font-weight:500; cursor:pointer; padding:2px 6px; border-radius:4px; }
.clear-btn:hover { background:#fef2f2; }
.file-list { list-style:none; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; background:#ffffff; max-height:160px; overflow-y:auto; }
.file-list li { border-bottom:1px solid #f1f5f9; display:flex; align-items:center; justify-content:space-between; padding:10px 12px; min-height:44px; gap:8px; font-size:13px; }
.file-list li:last-child { border-bottom:none; }
.file-item-left { display:flex; align-items:center; gap:8px; overflow:hidden; min-width:0; flex:1; text-align:left; }
.file-icon { color:#64748b; flex-shrink:0; }
.file-name { font-size:13px; font-weight:500; color:#0f172a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.file-meta { display:flex; align-items:center; gap:8px; flex-shrink:0; }
.file-size { font-size:11px; color:#64748b; background:#f1f5f9; padding:2px 6px; border-radius:6px; font-weight:500; white-space:nowrap; }
.remove-btn { background:none; border:none; color:#94a3b8; font-size:16px; cursor:pointer; padding:0 4px; line-height:1; }
.remove-btn:hover { color:#ef4444; }
.file-summary { font-size:12px; font-weight:600; color:#2563eb; margin-top:8px; text-align:center; }

/* Mode Selection */
.mode-section { margin-bottom:16px; text-align:left; }
.mode-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:6px; }
.mode-label-btn { display:flex; align-items:center; gap:6px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px; font-size:12px; font-weight:500; color:#0f172a; background:#f8fafc; cursor:pointer; transition:all 0.15s; }
.mode-label-btn:hover { border-color:#2563eb; background:#eff6ff; }
.mode-label-btn.selected { border-color:#2563eb; background:#eff6ff; color:#2563eb; font-weight:600; }
.mode-label-btn input { display:none; }

/* Active View: QR and Link */
.qr-card { margin-bottom:16px; display:flex; flex-direction:column; align-items:center; }
.qr-wrapper { background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:12px; box-shadow:0 2px 4px rgba(0,0,0,0.03); display:inline-block; }
.qr-wrapper svg { display:block; border-radius:6px; max-width:180px; max-height:180px; }
.pin-badge { margin-top:10px; font-size:13px; font-weight:600; color:#0f172a; background:#f1f5f9; padding:6px 14px; border-radius:8px; border:1px solid #e2e8f0; display:inline-flex; align-items:center; gap:6px; }
.pin-val { font-family:monospace; font-size:16px; font-weight:700; color:#2563eb; letter-spacing:2px; }
.url-badge { margin-top:8px; display:flex; align-items:center; justify-content:space-between; background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:8px 12px; width:100%; box-sizing:border-box; }
.url-text { font-size:12px; font-family:monospace; color:#2563eb; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; text-align:left; }
.copy-btn { background:#eff6ff; color:#2563eb; border:1px solid #bfdbfe; border-radius:6px; padding:4px 10px; font-size:11px; font-weight:600; cursor:pointer; transition:all 0.15s; margin-left:8px; flex-shrink:0; }
.copy-btn:hover { background:#dbeafe; }

/* Progress Container */
.progress-container { display:none; background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:16px; margin-top:14px; text-align:left; }
.progress-status { font-size:13px; font-weight:600; color:#0f172a; margin-bottom:10px; display:flex; align-items:center; gap:8px; }
.spinner { width:14px; height:14px; border:2px solid #cbd5e1; border-top-color:#2563eb; border-radius:50%; animation:spin 0.75s linear infinite; display:inline-block; flex-shrink:0; }
@keyframes spin { to { transform:rotate(360deg); } }
.progress-bar-bg { background:#e2e8f0; border-radius:6px; height:8px; overflow:hidden; }
.progress-bar-fill { background:#2563eb; height:100%; width:0%; transition:width 0.15s ease; border-radius:6px; }
.progress-info { display:flex; justify-content:space-between; margin-top:10px; font-size:12px; color:#64748b; font-weight:500; }

/* Buttons */
.submit-button { display:flex; align-items:center; justify-content:center; gap:8px; width:100%; padding:14px 20px;
                 background:#2563eb; color:#ffffff; border:none; border-radius:12px; font-size:15px; font-weight:600;
                 cursor:pointer; transition:all 0.15s; opacity:0.4; pointer-events:none; }
.submit-button.enabled { opacity:1; pointer-events:auto; box-shadow:0 1px 2px rgba(37,99,235,0.2); }
.submit-button.enabled:hover { background:#1d4ed8; }
.submit-button.enabled:active { transform:scale(0.99); }
.stop-button { display:flex; align-items:center; justify-content:center; gap:8px; width:100%; padding:12px 20px;
               background:#fef2f2; color:#dc2626; border:1px solid #fecaca; border-radius:12px; font-size:14px;
               font-weight:600; cursor:pointer; transition:all 0.15s; margin-top:12px; }
.stop-button:hover { background:#fee2e2; }
.footer { text-align:center; margin-top:24px; font-size:12px; color:#94a3b8; font-weight:500; }
</style>
</head>
<body>
<div class="container">
<div class="header">
  <div class="badge-icon">
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
  </div>
  <h1 id="page-title">Send Files</h1>
  <p class="subtitle" id="page-subtitle">Select files to share via QR code or link</p>
</div>

<!-- SECTION 1: SELECTION VIEW -->
<div id="selection-view">
  <div class="file-drop-area" id="drop-area">
    <input type="file" id="file-input" multiple>
    <div class="drop-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
    </div>
    <p class="drop-text" id="drop-text">Tap to select files</p>
    <p class="drop-hint">or drag and drop multiple files here</p>
  </div>

  <div id="file-preview-area" class="file-preview-area" style="display:none;">
    <div class="file-section-header">
      <div style="display:flex;align-items:center;gap:6px;">
        <span class="file-section-title">Selected Files</span>
        <span class="file-count-badge" id="file-count-badge">0</span>
      </div>
      <button type="button" class="clear-btn" id="clear-btn">Clear</button>
    </div>
    <ul class="file-list" id="file-list-preview"></ul>
    <div class="file-summary" id="file-summary"></div>
  </div>

  <div class="mode-section">
    <span class="file-section-title">Tunnel Mode</span>
    <div class="mode-grid">
      <label class="mode-label-btn selected" id="lbl-lan"><input type="radio" name="mode" value="LAN" checked> LAN (Local)</label>
      <label class="mode-label-btn" id="lbl-cf"><input type="radio" name="mode" value="Cloudflare"> Cloudflare</label>
      <label class="mode-label-btn" id="lbl-ssh"><input type="radio" name="mode" value="SSH"> SSH Tunnel</label>
      <label class="mode-label-btn" id="lbl-ngrok"><input type="radio" name="mode" value="Ngrok"> Ngrok</label>
    </div>
  </div>

  <button type="button" id="submit-btn" class="submit-button">Share Files</button>
</div>

<!-- SECTION 2: ACTIVE TRANSFER VIEW -->
<div id="active-view" style="display:none;">
  <div class="qr-card">
    <div class="qr-wrapper" id="qr-wrapper"></div>
    <p class="drop-hint" style="margin-top:8px;">Scan with another device to download</p>
    <div class="pin-badge" id="pin-badge-wrap">Access Code: <span class="pin-val" id="pin-val">----</span></div>
    <div class="url-badge">
      <span class="url-text" id="target-url-text">http://...</span>
      <button type="button" class="copy-btn" id="copy-btn">Copy Link</button>
    </div>
  </div>

  <div class="file-preview-area" id="active-files-area">
    <div class="file-section-header">
      <span class="file-section-title">Files Being Shared</span>
      <span class="file-count-badge" id="active-file-count-badge">0</span>
    </div>
    <ul class="file-list" id="active-file-list"></ul>
  </div>

  <div id="progress-container" class="progress-container">
    <div class="progress-status" id="progress-status">
      <span class="spinner" id="progress-spinner"></span>
      <span id="progress-status-text">Waiting for recipient to connect...</span>
    </div>
    <div class="progress-bar-bg"><div id="progress-bar" class="progress-bar-fill"></div></div>
    <div class="progress-info">
      <span id="progress-pct">0%</span>
      <span id="progress-speed">0 B/s</span>
      <span id="progress-stats">0 B / 0 B</span>
    </div>
  </div>

  <button type="button" id="stop-btn" class="stop-button">Stop Transfer & Close</button>
</div>

<p class="footer">qrtunnel</p>
</div>

<script>
let selectedFiles = [];
const fileInput = document.getElementById('file-input');
const dropArea = document.getElementById('drop-area');
const dropText = document.getElementById('drop-text');
const previewArea = document.getElementById('file-preview-area');
const listPreview = document.getElementById('file-list-preview');
const fileSummary = document.getElementById('file-summary');
const fileCountBadge = document.getElementById('file-count-badge');
const submitBtn = document.getElementById('submit-btn');
const clearBtn = document.getElementById('clear-btn');

const selectionView = document.getElementById('selection-view');
const activeView = document.getElementById('active-view');
const qrWrapper = document.getElementById('qr-wrapper');
const pinVal = document.getElementById('pin-val');
const targetUrlText = document.getElementById('target-url-text');
const copyBtn = document.getElementById('copy-btn');
const activeFileCountBadge = document.getElementById('active-file-count-badge');
const activeFileList = document.getElementById('active-file-list');

const progressContainer = document.getElementById('progress-container');
const progressSpinner = document.getElementById('progress-spinner');
const progressStatusText = document.getElementById('progress-status-text');
const progressBar = document.getElementById('progress-bar');
const progressPct = document.getElementById('progress-pct');
const progressSpeed = document.getElementById('progress-speed');
const progressStats = document.getElementById('progress-stats');
const stopBtn = document.getElementById('stop-btn');

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    var kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    var mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + ' MB';
    var gb = mb / 1024;
    return gb.toFixed(1) + ' GB';
}

function updateFileList() {
    listPreview.innerHTML = '';
    if (selectedFiles.length > 0) {
        let total = 0;
        selectedFiles.forEach((file, idx) => {
            total += file.size;
            const li = document.createElement('li');
            li.innerHTML = `
              <div class="file-item-left">
                <svg class="file-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span class="file-name" title="${file.name}">${file.name}</span>
              </div>
              <div class="file-meta">
                <span class="file-size">${formatBytes(file.size)}</span>
                <button type="button" class="remove-btn" data-idx="${idx}" title="Remove file">✕</button>
              </div>`;
            listPreview.appendChild(li);
        });
        fileCountBadge.textContent = selectedFiles.length;
        fileSummary.textContent = `${selectedFiles.length} ${selectedFiles.length === 1 ? 'file' : 'files'} selected (${formatBytes(total)})`;
        submitBtn.textContent = `Share ${selectedFiles.length} ${selectedFiles.length === 1 ? 'File' : 'Files'}`;
        submitBtn.classList.add('enabled');
        previewArea.style.display = 'block';
        dropText.textContent = 'Add more files';
    } else {
        fileCountBadge.textContent = '0';
        previewArea.style.display = 'none';
        submitBtn.textContent = 'Share Files';
        submitBtn.classList.remove('enabled');
        dropText.textContent = 'Tap to select files';
    }
}

fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
        for (let i = 0; i < fileInput.files.length; i++) {
            const f = fileInput.files[i];
            if (!selectedFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
                selectedFiles.push(f);
            }
        }
        fileInput.value = '';
        updateFileList();
    }
});

listPreview.addEventListener('click', (e) => {
    if (e.target.classList.contains('remove-btn')) {
        const idx = parseInt(e.target.getAttribute('data-idx'), 10);
        selectedFiles.splice(idx, 1);
        updateFileList();
    }
});

clearBtn.addEventListener('click', () => {
    selectedFiles = [];
    updateFileList();
});

['dragenter', 'dragover'].forEach(n => dropArea.addEventListener(n, (e) => {
    e.preventDefault();
    dropArea.classList.add('dragover');
}));
['dragleave', 'drop'].forEach(n => dropArea.addEventListener(n, (e) => {
    e.preventDefault();
    dropArea.classList.remove('dragover');
}));
dropArea.addEventListener('drop', (e) => {
    if (e.dataTransfer.files.length) {
        for (let i = 0; i < e.dataTransfer.files.length; i++) {
            const f = e.dataTransfer.files[i];
            if (!selectedFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
                selectedFiles.push(f);
            }
        }
        updateFileList();
    }
});

document.querySelectorAll('input[name="mode"]').forEach(radio => {
    radio.addEventListener('change', () => {
        document.querySelectorAll('.mode-label-btn').forEach(l => l.classList.remove('selected'));
        radio.closest('label').classList.add('selected');
    });
});

submitBtn.addEventListener('click', () => {
    if (!selectedFiles.length) return;
    submitBtn.classList.remove('enabled');
    submitBtn.textContent = 'Preparing Transfer...';

    const selectedMode = document.querySelector('input[name="mode"]:checked').value;
    const formData = new FormData();
    selectedFiles.forEach(f => formData.append('file', f));

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/sender/share?mode=${encodeURIComponent(selectedMode)}`, true);

    xhr.onload = () => {
        if (xhr.status === 200) {
            try {
                const res = JSON.parse(xhr.responseText);
                switchToActiveView(res);
            } catch (err) {
                alert('Transfer started');
            }
        } else {
            alert('Failed to start sharing: ' + xhr.statusText);
            submitBtn.classList.add('enabled');
            submitBtn.textContent = 'Share Files';
        }
    };
    xhr.onerror = () => {
        alert('Network error while starting transfer');
        submitBtn.classList.add('enabled');
        submitBtn.textContent = 'Share Files';
    };
    xhr.send(formData);
});

function switchToActiveView(data) {
    selectionView.style.display = 'none';
    activeView.style.display = 'block';
    document.getElementById('page-title').textContent = data.is_send !== false ? 'Sharing Files' : 'Receiving Files';
    document.getElementById('page-subtitle').textContent = data.is_send !== false ? 'Scan to download files' : 'Scan to send files';

    if (data.qr_svg) {
        qrWrapper.innerHTML = data.qr_svg;
    }
    pinVal.textContent = data.pin || '----';
    targetUrlText.textContent = data.target_url || '';

    activeFileList.innerHTML = '';
    const files = data.files || [];
    activeFileCountBadge.textContent = files.length;
    files.forEach(f => {
        const li = document.createElement('li');
        li.innerHTML = `
          <div class="file-item-left">
            <svg class="file-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span class="file-name" title="${f.name}">${f.name}</span>
          </div>
          <div class="file-meta">
            <span class="file-size">${formatBytes(f.size)}</span>
          </div>`;
        activeFileList.appendChild(li);
    });

    progressContainer.style.display = 'block';
    progressStatusText.textContent = 'Waiting for recipient to connect...';
}

copyBtn.addEventListener('click', () => {
    const url = targetUrlText.textContent;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(() => {
            copyBtn.textContent = 'Copied!';
            setTimeout(() => copyBtn.textContent = 'Copy Link', 1500);
        });
    }
});

// Initialize with current server state if already active
const initialState = __INITIAL_STATE__;
if (initialState && initialState.is_active) {
    switchToActiveView(initialState);
}

const evtSource = new EventSource('/api/sender/events');

evtSource.addEventListener('state', (e) => {
    const state = JSON.parse(e.data);
    if (state.is_active) {
        switchToActiveView(state);
    }
});

evtSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data);
    progressContainer.style.display = 'block';
    const pct = data.pct || 0;
    progressBar.style.width = pct + '%';
    progressPct.textContent = pct + '%';
    progressSpeed.textContent = formatBytes(data.speed || 0) + '/s';
    progressStats.textContent = `${formatBytes(data.transferred || 0)} / ${formatBytes(data.total || 0)}`;

    if (data.status === 'completed') {
        progressSpinner.style.display = 'none';
        progressStatusText.textContent = '✓ Transfer Complete!';
        progressBar.style.background = '#059669';
    } else {
        progressSpinner.style.display = 'inline-block';
        progressStatusText.textContent = data.label ? `Transferring ${data.label}...` : 'Transferring...';
        progressBar.style.background = '#2563eb';
    }
});

function showSessionEnded() {
    document.body.innerHTML = `
      <div class="container" style="text-align:center;padding:48px 24px;">
        <div class="badge-icon" style="background:#f1f5f9;color:#64748b;margin:0 auto 16px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
        </div>
        <h1 style="color:#0f172a;margin-bottom:8px;font-size:20px;font-weight:700;">Session Ended</h1>
        <p class="subtitle">qrtunnel has stopped. You can safely close this window.</p>
      </div>`;
}

evtSource.addEventListener('close', () => {
    showSessionEnded();
});

function closeNotification() {
    navigator.sendBeacon('/api/sender/close');
}
window.addEventListener('beforeunload', closeNotification);
window.addEventListener('pagehide', closeNotification);

setInterval(() => {
    fetch('/api/sender/heartbeat', { method: 'POST', keepalive: true }).catch(() => {});
}, 1500);

stopBtn.addEventListener('click', () => {
    fetch('/api/sender/stop', { method: 'POST' }).finally(() => {
        showSessionEnded();
    });
});
</script>
</body></html>""".replace("__INITIAL_STATE__", initial_state_json)

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(len(html.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def handle_sender_state(self):
        state = sender_sync.get_state()
        body = json.dumps(state).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def handle_sender_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        initial_msg = f"event: state\ndata: {json.dumps(sender_sync.get_state())}\n\n".encode()
        try:
            self.wfile.write(initial_msg)
            self.wfile.flush()
        except Exception:
            return

        q = sender_sync.subscribe()
        try:
            while not sender_sync.is_closed():
                try:
                    msg = q.get(timeout=1.0)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    try:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except Exception:
                        break
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            sender_sync.unsubscribe(q)

    def handle_sender_heartbeat(self):
        sender_sync.record_heartbeat()
        self.send_response(204)
        self.end_headers()

    def handle_sender_close(self):
        sender_sync.close_from_browser()
        self.send_response(204)
        self.end_headers()

    def handle_sender_stop(self):
        sender_sync.close_from_browser()
        self.send_response(204)
        self.end_headers()

    def handle_sender_share(self):
        try:
            content_length_str = self.headers.get("Content-Length")
            if not content_length_str:
                self.send_error(411, "Length Required")
                return
            content_length = int(content_length_str)

            staging_dir = Config.CONFIG_DIR / "staged" / str(int(time.time()))
            staging_dir.mkdir(parents=True, exist_ok=True)

            stream = LimitedStream(self.rfile, content_length)
            parser = StreamingFormDataParser(headers=self.headers)
            target = MultiFileTarget(staging_dir)
            parser.register("file", target)

            chunk_size = 65536
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                parser.data_received(chunk)

            if not target.files:
                target.cleanup()
                self.send_error(400, "No files found in form data")
                return

            saved_paths = []
            for raw_filename, tmp_path in target.files:
                sanitized_filename = os.path.basename(unquote(raw_filename))
                if not sanitized_filename:
                    sanitized_filename = f"shared_{uuid.uuid4().hex[:6]}"
                base_stem = Path(sanitized_filename).stem
                base_ext = Path(sanitized_filename).suffix
                saved_filename = sanitized_filename
                counter = 1
                final_path = staging_dir / saved_filename
                while final_path.exists():
                    saved_filename = f"{base_stem} ({counter}){base_ext}"
                    final_path = staging_dir / saved_filename
                    counter += 1
                os.rename(tmp_path, final_path)
                saved_paths.append(str(final_path))

            FileTransferHandler.file_paths = saved_paths
            FileTransferHandler.upload_mode = False

            # Query params for mode
            mode_name = "LAN"
            parsed_query = parse_qs(urlparse(self.path).query)
            if "mode" in parsed_query:
                mode_name = parsed_query["mode"][0]

            from .tunnels import TunnelManager

            current_lan_ip = self.server_lan_ip or get_lan_ip()
            lan_url = (
                f"http://{current_lan_ip}:{Config.LOCAL_PORT}"
                if current_lan_ip
                else f"http://localhost:{Config.LOCAL_PORT}"
            )

            target_url = lan_url
            if mode_name != "LAN":
                tunnel_backend = mode_name.lower() if mode_name in ("Cloudflare", "Ngrok") else None
                noauth = mode_name != "Ngrok"
                tm = TunnelManager(
                    Config.LOCAL_PORT,
                    noauth=noauth,
                    lan_only=False,
                    lan_ip=current_lan_ip,
                    tunnel_backend=tunnel_backend,
                )
                if tm.start():
                    sender_sync.tunnel_manager = tm
                    target_url = tm.public_url or tm.lan_url

            qr_svg = generate_qr_svg(target_url)

            sender_sync.set_active_transfer(
                is_send=True,
                file_paths=saved_paths,
                mode_name=mode_name,
                port=Config.LOCAL_PORT,
                target_url=target_url,
                pin=Config.OTP,
                qr_svg=qr_svg,
            )

            print("\n" + "=" * 60)
            print("Files selected via Sender UI:")
            for fp in saved_paths:
                print(f"  - {os.path.basename(fp)} ({format_size(os.path.getsize(fp))})")
            print("=" * 60)
            from .qr import generate_qr_code

            generate_qr_code(target_url)

            resp_data = {
                "success": True,
                "is_send": True,
                "target_url": target_url,
                "pin": Config.OTP,
                "files": [
                    {"name": os.path.basename(p), "size": os.path.getsize(p)} for p in saved_paths
                ],
                "qr_svg": qr_svg,
            }
            body = json.dumps(resp_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"{ERR} Error in handle_sender_share: {e}")
            self.send_error(500, "Internal Server Error")

    def send_upload_page(self):
        html = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - File Upload</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:#f8fafc; color:#0f172a; min-height:100vh; display:flex; flex-direction:column;
       align-items:center; justify-content:center; padding:20px 16px; -webkit-font-smoothing:antialiased; }
.container { background:#ffffff; border:1px solid #e2e8f0; border-radius:16px; padding:32px 24px;
             box-shadow:0 4px 6px -1px rgba(0,0,0,0.05),0 2px 4px -2px rgba(0,0,0,0.05);
             max-width:440px; width:100%; }
@media (max-width:480px) { .container { padding:24px 18px; border-radius:14px; } }
.header { text-align:center; margin-bottom:24px; }
.badge-icon { display:inline-flex; align-items:center; justify-content:center; width:48px; height:48px;
              border-radius:12px; background:#eff6ff; color:#2563eb; margin-bottom:12px; }
h1 { font-size:20px; font-weight:700; color:#0f172a; margin-bottom:4px; letter-spacing:-0.3px; }
.subtitle { font-size:14px; color:#64748b; font-weight:400; }
.upload-form { display:flex; flex-direction:column; gap:16px; }
.file-drop-area { position:relative; border:2px dashed #cbd5e1; border-radius:14px; padding:32px 16px;
                  text-align:center; background:#f8fafc; cursor:pointer; transition:all 0.15s ease; }
.file-drop-area:hover, .file-drop-area.dragover { border-color:#2563eb; background:#eff6ff; }
#file-input { position:absolute; top:0; left:0; width:100%; height:100%; opacity:0; cursor:pointer; }
.drop-icon { display:inline-flex; align-items:center; justify-content:center; width:44px; height:44px;
             border-radius:10px; background:#fff; border:1px solid #e2e8f0; color:#2563eb;
             margin-bottom:10px; box-shadow:0 1px 3px rgba(0,0,0,0.05); }
.drop-text { font-size:14px; font-weight:600; color:#0f172a; margin-bottom:2px; }
.drop-hint { font-size:12px; color:#64748b; }
.file-preview-area { margin-top:12px; text-align:left; }
.file-summary { font-size:13px; font-weight:600; color:#2563eb; margin-bottom:8px; text-align:center; }
.file-list-preview { list-style:none; border:1px solid #e2e8f0; border-radius:10px; max-height:160px; overflow-y:auto; background:#ffffff; }
.file-list-preview li { display:flex; justify-content:space-between; align-items:center; padding:8px 12px; border-bottom:1px solid #f1f5f9; font-size:12px; color:#0f172a; }
.file-list-preview li:last-child { border-bottom:none; }
.file-preview-name { font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:70%; }
.file-preview-size { color:#64748b; font-size:11px; white-space:nowrap; }
.progress-container { display:none; background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:16px; }
.progress-bar-bg { background:#e2e8f0; border-radius:6px; height:8px; overflow:hidden; }
.progress-bar-fill { background:#2563eb; height:100%; width:0%; transition:width 0.15s ease; border-radius:6px; }
.progress-info { display:flex; justify-content:space-between; margin-top:10px; font-size:12px; color:#64748b; font-weight:500; }
.submit-button { display:flex; align-items:center; justify-content:center; gap:8px; width:100%; padding:14px 20px;
                 background:#2563eb; color:#ffffff; border:none; border-radius:12px; font-size:15px; font-weight:600;
                 cursor:pointer; transition:all 0.15s; opacity:0.4; pointer-events:none; }
.submit-button.enabled { opacity:1; pointer-events:auto; box-shadow:0 1px 2px rgba(37,99,235,0.2); }
.submit-button.enabled:hover { background:#1d4ed8; }
.submit-button.enabled:active { transform:scale(0.99); }
.footer { text-align:center; margin-top:24px; font-size:12px; color:#94a3b8; font-weight:500; }
</style></head><body>
<div class="container">
<div class="header">
<div class="badge-icon">
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
</div>
<h1>Send Files</h1>
<p class="subtitle">Select files to send to this computer</p>
</div>
<form id="upload-form" class="upload-form" action="/upload" method="post" enctype="multipart/form-data">
<div class="file-drop-area" id="drop-area">
  <input type="file" id="file-input" name="file" multiple required>
  <div class="drop-icon">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
  </div>
  <p class="drop-text" id="drop-text">Tap to select files</p>
  <p class="drop-hint">or drag and drop multiple files here</p>
</div>
<div id="file-preview-area" class="file-preview-area" style="display:none;">
  <div id="file-summary" class="file-summary"></div>
  <ul id="file-list-preview" class="file-list-preview"></ul>
</div>
<div id="progress-container" class="progress-container">
  <div class="progress-bar-bg"><div id="progress-bar" class="progress-bar-fill"></div></div>
  <div class="progress-info">
    <span id="progress-pct">0%</span>
    <span id="progress-speed">0 B/s</span>
    <span id="progress-stats">0 B / 0 B</span>
  </div>
</div>
<button type="submit" id="submit-btn" class="submit-button">Upload Files</button>
</form>
<p class="footer">qrtunnel</p>
</div>
<script>
const fileInput = document.getElementById('file-input');
const dropText = document.getElementById('drop-text');
const filePreviewArea = document.getElementById('file-preview-area');
const fileSummary = document.getElementById('file-summary');
const fileListPreview = document.getElementById('file-list-preview');
const submitButton = document.getElementById('submit-btn');
const uploadForm = document.getElementById('upload-form');
const progressContainer = document.getElementById('progress-container');
const progressBar = document.getElementById('progress-bar');
const progressPct = document.getElementById('progress-pct');
const progressSpeed = document.getElementById('progress-speed');
const progressStats = document.getElementById('progress-stats');

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    var kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    var mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + ' MB';
    var gb = mb / 1024;
    return gb.toFixed(1) + ' GB';
}

fileInput.addEventListener('change', () => {
    fileListPreview.innerHTML = '';
    if (fileInput.files.length > 0) {
        var totalBytes = 0;
        for (var i = 0; i < fileInput.files.length; i++) {
            totalBytes += fileInput.files[i].size;
            var li = document.createElement('li');
            var nameSpan = document.createElement('span');
            nameSpan.className = 'file-preview-name';
            nameSpan.textContent = fileInput.files[i].name;
            var sizeSpan = document.createElement('span');
            sizeSpan.className = 'file-preview-size';
            sizeSpan.textContent = formatBytes(fileInput.files[i].size);
            li.appendChild(nameSpan);
            li.appendChild(sizeSpan);
            fileListPreview.appendChild(li);
        }
        if (fileInput.files.length === 1) {
            fileSummary.textContent = '1 file selected (' + formatBytes(totalBytes) + ')';
            submitButton.textContent = 'Upload File';
        } else {
            fileSummary.textContent = fileInput.files.length + ' files selected (' + formatBytes(totalBytes) + ')';
            submitButton.textContent = 'Upload ' + fileInput.files.length + ' Files';
        }
        filePreviewArea.style.display = 'block';
        dropText.textContent = fileInput.files.length === 1 ? 'Change selected file' : 'Change selected files';
        submitButton.classList.add('enabled');
    } else {
        filePreviewArea.style.display = 'none';
        dropText.textContent = 'Tap to select files';
        submitButton.textContent = 'Upload Files';
        submitButton.classList.remove('enabled');
    }
});

uploadForm.addEventListener('submit', (e) => {
    if (!fileInput.files.length) return;
    e.preventDefault();
    submitButton.classList.remove('enabled');
    submitButton.style.opacity = '0.4';
    submitButton.style.pointerEvents = 'none';
    submitButton.textContent = 'Uploading...';
    progressContainer.style.display = 'block';

    var formData = new FormData();
    for (var i = 0; i < fileInput.files.length; i++) {
        formData.append('file', fileInput.files[i]);
    }

    var xhr = new XMLHttpRequest();
    var lastLoaded = 0;
    var lastTime = Date.now();

    xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
            var now = Date.now();
            var pct = ((ev.loaded / ev.total) * 100).toFixed(1);
            progressBar.style.width = pct + '%';
            progressPct.textContent = pct + '%';
            progressStats.textContent = formatBytes(ev.loaded) + ' / ' + formatBytes(ev.total);

            var elapsedSec = (now - lastTime) / 1000;
            if (elapsedSec >= 0.4) {
                var speed = (ev.loaded - lastLoaded) / elapsedSec;
                progressSpeed.textContent = formatBytes(speed) + '/s';
                lastLoaded = ev.loaded;
                lastTime = now;
            }

            if (ev.loaded >= ev.total) {
                submitButton.textContent = 'Processing on server...';
            }
        }
    };

    xhr.onload = () => {
        if (xhr.status === 200) {
            document.open();
            document.write(xhr.responseText);
            document.close();
        } else {
            alert('Upload failed: ' + xhr.statusText);
            submitButton.classList.add('enabled');
            submitButton.style.opacity = '1';
            submitButton.style.pointerEvents = 'auto';
            submitButton.textContent = 'Upload Files';
        }
    };

    xhr.onerror = () => {
        alert('Network error occurred during upload.');
        submitButton.classList.add('enabled');
        submitButton.style.opacity = '1';
        submitButton.style.pointerEvents = 'auto';
        submitButton.textContent = 'Upload Files';
    };

    xhr.open('POST', '/upload', true);
    xhr.send(formData);
});
</script>
</body></html>"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(len(html.encode())))
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
            display_name = f"{os.path.basename(os.path.dirname(fp))}/{fn}" if has_duplicates else fn
            size_label = format_size(os.path.getsize(fp)) if os.path.isfile(fp) else "folder"
            file_list_html += f"""<li class="file-item">
  <div class="file-cb-wrap">
    <input type="checkbox" class="file-cb" id="cb-{idx}" data-idx="{idx}" data-name="{fn}">
  </div>
  <label for="cb-{idx}" class="file-info" title="Select {display_name}">
    <svg class="file-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
    <span class="file-name">{display_name}</span>
  </label>
  <div class="file-meta">
    <span class="file-size">{size_label}</span>
    <a href="{href_path}" class="dl-single-btn" download title="Download this file individually">
      <svg class="dl-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    </a>
  </div>
</li>"""
        template = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - File Download</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:#f8fafc; color:#0f172a; min-height:100vh; display:flex; flex-direction:column;
       align-items:center; justify-content:center; padding:20px 16px; -webkit-font-smoothing:antialiased; }
.container { background:#ffffff; border:1px solid #e2e8f0; border-radius:16px; padding:32px 24px;
             box-shadow:0 4px 6px -1px rgba(0,0,0,0.05),0 2px 4px -2px rgba(0,0,0,0.05);
             max-width:440px; width:100%; }
@media (max-width:480px) { .container { padding:24px 18px; border-radius:14px; } }
.header { text-align:center; margin-bottom:24px; }
.badge-icon { display:inline-flex; align-items:center; justify-content:center; width:48px; height:48px;
              border-radius:12px; background:#eff6ff; color:#2563eb; margin-bottom:12px; }
h1 { font-size:20px; font-weight:700; color:#0f172a; margin-bottom:4px; letter-spacing:-0.3px; }
.subtitle { font-size:14px; color:#64748b; font-weight:400; }
.file-section { margin-bottom:20px; }
.file-section-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
.select-btn { background:#eff6ff; color:#2563eb; border:1px solid #bfdbfe; border-radius:6px; padding:4px 10px; font-size:12px; font-weight:600; cursor:pointer; transition:all 0.15s; }
.select-btn:hover { background:#dbeafe; }
.file-section-title { font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:#94a3b8; }
.file-count-badge { font-size:11px; font-weight:600; color:#2563eb; background:#eff6ff; padding:2px 8px; border-radius:12px; }
.file-list { list-style:none; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; background:#ffffff; }
.file-list li { border-bottom:1px solid #f1f5f9; display:flex; align-items:center; padding:10px 14px; min-height:48px; gap:10px; }
.file-list li:last-child { border-bottom:none; }
.file-cb-wrap { display:flex; align-items:center; justify-content:center; }
.file-cb { width:17px; height:17px; accent-color:#2563eb; cursor:pointer; }
.file-info { display:flex; align-items:center; gap:8px; overflow:hidden; min-width:0; flex:1; cursor:pointer; user-select:none; }
.file-icon { color:#64748b; flex-shrink:0; }
.file-name { font-size:14px; font-weight:500; color:#0f172a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.file-meta { display:flex; align-items:center; gap:8px; flex-shrink:0; }
.file-size { font-size:12px; color:#64748b; background:#f1f5f9; padding:3px 8px; border-radius:6px; font-weight:500; white-space:nowrap; }
.dl-single-btn { display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px; border-radius:8px; background:#f8fafc; border:1px solid #e2e8f0; color:#2563eb; text-decoration:none; transition:all 0.15s; }
.dl-single-btn:hover { background:#2563eb; color:#ffffff; border-color:#2563eb; }
.dl-arrow { flex-shrink:0; }
.selected-button { display:flex; align-items:center; justify-content:center; gap:8px; width:100%; padding:14px 20px;
                  background:#059669; color:#ffffff; border:none; border-radius:12px; font-size:15px; font-weight:600;
                  cursor:pointer; transition:background 0.15s, transform 0.1s; margin-top:14px; box-shadow:0 1px 2px rgba(5,150,105,0.2); }
.selected-button:hover { background:#047857; }
.selected-button:active { transform:scale(0.99); }
.progress-container { display:none; background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:16px; margin-top:14px; text-align:left; }
.progress-status { font-size:13px; font-weight:600; color:#0f172a; margin-bottom:10px; display:flex; align-items:center; gap:8px; }
.spinner { width:14px; height:14px; border:2px solid #cbd5e1; border-top-color:#2563eb; border-radius:50%; animation:spin 0.75s linear infinite; display:inline-block; flex-shrink:0; }
@keyframes spin { to { transform:rotate(360deg); } }
.progress-bar-bg { background:#e2e8f0; border-radius:6px; height:8px; overflow:hidden; }
.progress-bar-fill { background:#2563eb; height:100%; width:0%; transition:width 0.15s ease; border-radius:6px; }
.progress-info { display:flex; justify-content:space-between; margin-top:10px; font-size:12px; color:#64748b; font-weight:500; }
.footer { text-align:center; margin-top:24px; font-size:12px; color:#94a3b8; font-weight:500; }
</style></head><body>
<div class="container">
<div class="header">
<div class="badge-icon">
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
</div>
<h1>Download Files</h1>
<p class="subtitle">Download files individually or select files to bundle as a zip</p>
</div>
<div class="file-section">
<div class="file-section-header">
  <div style="display:flex;align-items:center;gap:10px;">
    <button type="button" id="select-all-btn" class="select-btn">Select All</button>
    <span class="file-section-title">Files</span>
  </div>
  <span class="file-count-badge">__FILE_COUNT__</span>
</div>
<ul class="file-list">__FILE_LIST__</ul>
<div id="progress-container" class="progress-container">
  <div class="progress-status" id="progress-status">
    <span class="spinner" id="progress-spinner"></span>
    <span id="progress-status-text">Zipping selected files on host...</span>
  </div>
  <div class="progress-bar-bg"><div id="progress-bar" class="progress-bar-fill"></div></div>
  <div class="progress-info">
    <span id="progress-pct">0%</span>
    <span id="progress-speed">0 B/s</span>
    <span id="progress-stats">0 B / 0 B</span>
  </div>
</div>
<button type="button" id="download-selected-btn" class="selected-button" style="display:none;">
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
  <span id="selected-btn-text">Download Selected (.zip)</span>
</button>
</div>
<p class="footer">qrtunnel</p>
</div>
<script>
const checkboxes = document.querySelectorAll('.file-cb');
const selectAllBtn = document.getElementById('select-all-btn');
const dlSelectedBtn = document.getElementById('download-selected-btn');
const selectedBtnText = document.getElementById('selected-btn-text');
const progressContainer = document.getElementById('progress-container');
const progressStatusText = document.getElementById('progress-status-text');
const progressSpinner = document.getElementById('progress-spinner');
const progressBar = document.getElementById('progress-bar');
const progressPct = document.getElementById('progress-pct');
const progressSpeed = document.getElementById('progress-speed');
const progressStats = document.getElementById('progress-stats');

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    var kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    var mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + ' MB';
    var gb = mb / 1024;
    return gb.toFixed(1) + ' GB';
}

function updateSelection() {
    var checked = Array.from(checkboxes).filter(cb => cb.checked);
    var count = checked.length;
    if (count > 0) {
        dlSelectedBtn.style.display = 'flex';
        selectedBtnText.textContent = count === 1 ? 'Download Selected (1 file as .zip)' : 'Download Selected (' + count + ' files as .zip)';
    } else {
        dlSelectedBtn.style.display = 'none';
    }
    if (selectAllBtn) {
        selectAllBtn.textContent = count === checkboxes.length ? 'Deselect All' : 'Select All';
    }
}

checkboxes.forEach(cb => cb.addEventListener('change', updateSelection));

if (selectAllBtn) {
    selectAllBtn.addEventListener('click', () => {
        var allChecked = Array.from(checkboxes).every(cb => cb.checked);
        checkboxes.forEach(cb => cb.checked = !allChecked);
        updateSelection();
    });
}

function downloadWithProgress(url, defaultFilename, isZip) {
    progressContainer.style.display = 'block';
    progressSpinner.style.display = 'inline-block';
    progressBar.style.width = '0%';
    progressPct.textContent = '0%';
    progressSpeed.textContent = '';
    progressStats.textContent = isZip ? 'Zipping files on host...' : 'Connecting...';
    progressStatusText.textContent = isZip ? 'Zipping selected files on host...' : 'Requesting ' + defaultFilename + '...';

    if (dlSelectedBtn) {
        dlSelectedBtn.style.opacity = '0.5';
        dlSelectedBtn.style.pointerEvents = 'none';
        selectedBtnText.textContent = isZip ? 'Zipping in progress...' : 'Downloading...';
    }

    var xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    xhr.responseType = 'blob';

    var lastLoaded = 0;
    var lastTime = Date.now();

    xhr.onprogress = (ev) => {
        progressSpinner.style.display = 'none';
        progressStatusText.textContent = isZip ? 'Downloading ZIP archive...' : 'Downloading ' + defaultFilename + '...';

        if (ev.lengthComputable && ev.total > 0) {
            var now = Date.now();
            var pct = ((ev.loaded / ev.total) * 100).toFixed(1);
            progressBar.style.width = pct + '%';
            progressPct.textContent = pct + '%';
            progressStats.textContent = formatBytes(ev.loaded) + ' / ' + formatBytes(ev.total);

            var elapsedSec = (now - lastTime) / 1000;
            if (elapsedSec >= 0.3) {
                var speed = (ev.loaded - lastLoaded) / elapsedSec;
                progressSpeed.textContent = formatBytes(speed) + '/s';
                lastLoaded = ev.loaded;
                lastTime = now;
            }
        } else {
            progressPct.textContent = '';
            progressStats.textContent = formatBytes(ev.loaded) + ' downloaded';
        }
    };

    xhr.onload = () => {
        if (xhr.status === 200) {
            progressBar.style.width = '100%';
            progressPct.textContent = '100%';
            progressSpinner.style.display = 'none';
            progressStatusText.textContent = '✓ Download Complete!';

            var filename = defaultFilename;
            var disposition = xhr.getResponseHeader('Content-Disposition');
            if (disposition && disposition.indexOf('filename=') !== -1) {
                var match = disposition.match(/filename=["']?([^"';]+)["']?/);
                if (match && match[1]) {
                    filename = match[1];
                }
            }

            var blob = xhr.response;
            var downloadUrl = window.URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.style.display = 'none';
            a.href = downloadUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                document.body.removeChild(a);
                window.URL.revokeObjectURL(downloadUrl);
            }, 500);

            setTimeout(() => {
                if (dlSelectedBtn) {
                    dlSelectedBtn.style.opacity = '1';
                    dlSelectedBtn.style.pointerEvents = 'auto';
                    updateSelection();
                }
            }, 1500);
        } else {
            progressSpinner.style.display = 'none';
            progressStatusText.textContent = '⚠ Download failed (' + xhr.status + ')';
            alert('Download failed: ' + xhr.statusText);
            if (dlSelectedBtn) {
                dlSelectedBtn.style.opacity = '1';
                dlSelectedBtn.style.pointerEvents = 'auto';
                updateSelection();
            }
        }
    };

    xhr.onerror = () => {
        progressSpinner.style.display = 'none';
        progressStatusText.textContent = '⚠ Network error';
        alert('Network error occurred during download.');
        if (dlSelectedBtn) {
            dlSelectedBtn.style.opacity = '1';
            dlSelectedBtn.style.pointerEvents = 'auto';
            updateSelection();
        }
    };

    xhr.send();
}

if (dlSelectedBtn) {
    dlSelectedBtn.addEventListener('click', () => {
        var checkedIndices = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.getAttribute('data-idx'));
        if (!checkedIndices.length) return;
        var url = '/download/selected.zip?files=' + checkedIndices.join(',');
        downloadWithProgress(url, 'qrtunnel-selected.zip', true);
    });
}

document.querySelectorAll('.dl-single-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        e.preventDefault();
        var url = btn.getAttribute('href');
        var row = btn.closest('.file-item');
        var nameSpan = row ? row.querySelector('.file-name') : null;
        var displayName = nameSpan ? nameSpan.textContent.trim() : 'file';
        downloadWithProgress(url, displayName, false);
    });
});
</script>
</body></html>"""
        html = template.replace("__FILE_LIST__", file_list_html).replace(
            "__FILE_COUNT__", str(len(self.file_paths))
        )
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(len(html.encode())))
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
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
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
            self.send_header("Content-Disposition", f'attachment; filename="{dir_name}.zip"')
            self.send_header("Content-Length", str(total_size))
            self._send_auth_cookie_if_needed()
            self.end_headers()
            sent = 0
            chunk_size = 1048576  # 1 MB
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

    def serve_selected_zip(self):
        try:
            parsed = urlparse(self.path)
            from urllib.parse import parse_qs

            qs = parse_qs(parsed.query)
            file_indices = qs.get("files", [""])[0].split(",")
            selected_paths = []
            for idx_s in file_indices:
                idx_s = idx_s.strip()
                if idx_s.isdigit():
                    idx = int(idx_s)
                    if 0 <= idx < len(self.file_paths):
                        selected_paths.append(self.file_paths[idx])

            if not selected_paths:
                self.send_error(400, "No files selected")
                return

            self.serve_zip_archive(file_paths=selected_paths, zip_name="qrtunnel-selected.zip")
        except Exception as e:
            print(f"{ERR} Error serving selected ZIP archive: {e}")
            self.send_error(500, "Internal Server Error")

    def serve_zip_archive(self, file_paths=None, zip_name="qrtunnel-files.zip"):
        try:
            data = self.build_zip_archive(file_paths=file_paths)
            total_size = len(data)
            self.send_response(200)
            self.send_header("Content-type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{zip_name}"')
            self.send_header("Content-Length", str(total_size))
            self.send_header("Access-Control-Expose-Headers", "Content-Disposition, Content-Length")
            self._send_auth_cookie_if_needed()
            self.end_headers()
            sent = 0
            chunk_size = 1048576  # 1 MB
            last_update = 0
            while sent < total_size:
                chunk = data[sent : sent + chunk_size]
                self.wfile.write(chunk)
                sent += len(chunk)
                last_update = self.print_progress(
                    f"Download {zip_name}", sent, total_size, last_update=last_update
                )
            self.print_progress(f"Download {zip_name}", sent, total_size, force=True)
            print()
            print(f"{OK} ZIP archive served to {self.client_address[0]}")
            log_transfer(zip_name, total_size, self.client_address[0], "send")
        except BrokenPipeError:
            print(f"\n{ERR} Client disconnected during ZIP transfer")
        except Exception as e:
            print(f"{ERR} Error serving ZIP archive: {e}")
            self.send_error(500, "Internal Server Error")

    def serve_single_file(self, filename):
        if filename == "all.zip":
            self.serve_zip_archive()
            return
        if filename == "selected.zip":
            self.serve_selected_zip()
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
            self.send_header(
                "Content-Disposition", f'attachment; filename="{os.path.basename(target_path)}"'
            )
            self.send_header("Content-Length", str(content_length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Expose-Headers", "Content-Disposition, Content-Length")
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
