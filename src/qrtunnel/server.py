"""HTTP handlers for file download and upload."""

import hashlib
import http.cookies
import io
import json
import mimetypes
import os
import platform
import queue
import re
import socket
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
    store_cached_checksum,
)
from .zip_stream import (
    calculate_zip_size,
    collect_zip_entries,
    stream_zip_archive,
)

_stdout_lock = threading.Lock()


class ActiveTransferTracker:
    """Thread-safe transfer coordinator aggregating parallel range and multi-stream transfers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._transfers = {}

    def start_stream(self, client_ip, path, file_size, is_range):
        with self._lock:
            key = (client_ip, str(path))
            if key not in self._transfers:
                self._transfers[key] = {
                    "sent": 0,
                    "file_size": file_size,
                    "streams": 1,
                    "is_range": is_range,
                }
            else:
                self._transfers[key]["streams"] += 1

    def update_sent(self, client_ip, path, n_bytes):
        with self._lock:
            key = (client_ip, str(path))
            if key in self._transfers:
                self._transfers[key]["sent"] += n_bytes
                return min(self._transfers[key]["file_size"], self._transfers[key]["sent"]), self._transfers[key]["file_size"]
            return n_bytes, 0

    def finish_stream(self, client_ip, path):
        with self._lock:
            key = (client_ip, str(path))
            if key in self._transfers:
                self._transfers[key]["streams"] -= 1
                if self._transfers[key]["streams"] <= 0:
                    del self._transfers[key]
                    return True
            return False


_transfer_tracker = ActiveTransferTracker()


class MultiFileTarget(BaseTarget):
    """StreamingFormData target that handles multiple uploaded files with on-the-fly hashing."""

    def __init__(self, upload_dir):
        super().__init__()
        self.upload_dir = Path(upload_dir)
        self.files = []
        self.checksums = {}
        self._current_fd = None
        self._current_tmp = None
        self._current_filename = None
        self._current_hasher = None

    def on_start(self):
        self._current_filename = self.multipart_filename
        if self._current_filename and self._current_filename.strip():
            self._current_tmp = self.upload_dir / f"upload_{uuid.uuid4().hex}.tmp"
            self._current_fd = open(self._current_tmp, "wb", buffering=1048576)
            self._current_hasher = hashlib.sha256()
        else:
            self._current_tmp = None
            self._current_fd = None
            self._current_hasher = None

    def on_data_received(self, chunk: bytes):
        if self._current_fd:
            self._current_fd.write(chunk)
            if self._current_hasher:
                self._current_hasher.update(chunk)

    def on_finish(self):
        if self._current_fd:
            self._current_fd.close()
            self._current_fd = None
            checksum = self._current_hasher.hexdigest() if self._current_hasher else None
            self._current_hasher = None
            if self._current_filename and self._current_filename.strip():
                self.files.append((self._current_filename, self._current_tmp))
                if checksum:
                    self.checksums[self._current_tmp] = checksum
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
        self.checksums.clear()
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

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()

    def get_request(self):
        sock, addr = super().get_request()
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        return sock, addr


class FileTransferHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    wbufsize = 65536
    file_paths = None
    upload_mode = False
    server_lan_ip = None
    authorized_sessions = set()
    public_url = None
    lan_url = None

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
        if self.path in (
            "/ping",
            "/api/session/status",
            "/api/receiver/events",
        ) or self.path.startswith(
            ("/ping?", "/api/session/status?", "/api/receiver/events?")
        ):
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

    @staticmethod
    def get_receiver_session_script():
        return """<script>
(function() {
    function showSessionClosed() {
        if (document.getElementById('session-closed-overlay')) return;
        var overlay = document.createElement('div');
        overlay.id = 'session-closed-overlay';
        overlay.style.position = 'fixed';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100vw';
        overlay.style.height = '100vh';
        overlay.style.background = '#f8fafc';
        overlay.style.display = 'flex';
        overlay.style.flexDirection = 'column';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.padding = '20px 16px';
        overlay.style.zIndex = '999999';
        overlay.style.boxSizing = 'border-box';
        overlay.style.fontFamily = '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif';
        overlay.innerHTML = `
          <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;padding:36px 24px;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05),0 2px 4px -2px rgba(0,0,0,0.05);max-width:440px;width:100%;text-align:center;">
            <div style="display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;border-radius:50%;background:#f1f5f9;color:#64748b;margin:0 auto 16px;">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            </div>
            <h1 style="font-size:20px;font-weight:700;color:#0f172a;margin-bottom:8px;letter-spacing:-0.3px;">Session Closed</h1>
            <p style="font-size:14px;color:#64748b;line-height:1.5;margin:0;">The session has closed. You can safely close this window.</p>
          </div>
        `;
        document.body.appendChild(overlay);
    }

    try {
        var es = new EventSource('/api/receiver/events');
        es.addEventListener('close', function() {
            showSessionClosed();
        });
        es.addEventListener('error', function() {
            fetch('/api/session/status', { cache: 'no-store' })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d && d.closed) showSessionClosed();
                })
                .catch(function() {
                    setTimeout(function() {
                        fetch('/api/session/status', { cache: 'no-store' })
                            .catch(function() { showSessionClosed(); });
                    }, 1000);
                });
        });
    } catch(e) {}

    var failedCount = 0;
    var checkInterval = setInterval(function() {
        fetch('/api/session/status', { cache: 'no-store' })
            .then(function(res) {
                if (!res.ok) throw new Error('status ' + res.status);
                return res.json();
            })
            .then(function(data) {
                if (data && data.closed) {
                    showSessionClosed();
                    clearInterval(checkInterval);
                } else {
                    failedCount = 0;
                }
            })
            .catch(function() {
                failedCount++;
                if (failedCount >= 2) {
                    showSessionClosed();
                    clearInterval(checkInterval);
                }
            });
    }, 2000);
})();
</script>"""

    def send_login_page(self, error=None):
        error_html = f'<div class="error">{error}</div>' if error else ""
        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - Security Check</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }}
a, a:hover, a:visited, a:focus, a:active {{ text-decoration:none !important; color:inherit; outline:none; }}
button {{ font-family:inherit; outline:none; }}
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
        html = html.replace("</body>", f"{self.get_receiver_session_script()}</body>")
        self.send_response(200 if not error else 403)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode())))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
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

        # Sender & Receiver Web UI & API routes (local access)
        if is_local:
            if parsed_path.path in ("/sender", "/sender/", "/sender.html") or (
                parsed_path.path in ("/", "/index.html")
                and not self.file_paths
                and not self.upload_mode
            ):
                self.send_sender_page()
                return
            if parsed_path.path in ("/receive", "/receive/", "/receive.html") or (
                parsed_path.path in ("/", "/index.html")
                and self.upload_mode
            ):
                self.send_receive_page()
                return
            if parsed_path.path == "/api/sender/state":
                self.handle_sender_state()
                return
            if parsed_path.path == "/api/sender/events":
                self.handle_sender_events()
                return

        # Receiver session endpoints
        if parsed_path.path == "/api/session/status":
            self.handle_session_status()
            return
        if parsed_path.path == "/api/receiver/events":
            self.handle_receiver_events()
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

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        is_local = self.client_address[0] in ("127.0.0.1", "::1")

        # Sender & Receiver API routes (local access)
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
            if parsed_path.path == "/api/sender/port":
                self.handle_sender_port()
                return
            if parsed_path.path == "/api/receiver/mode":
                self.handle_receiver_mode()
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
            chunk_size = 262144
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
                checksum = getattr(target, "checksums", {}).get(tmp_path)
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
                sender_sync.record_received_file(saved_filename, file_size)
                print(f"{OK} File '{saved_filename}' received and saved to {final_path}")
                if checksum:
                    store_cached_checksum(final_path, checksum)
                    print(f"{OK} SHA256: {checksum}")
                else:
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
            encoded_success = success_html.encode("utf-8")
            self.send_header("Content-Length", str(len(encoded_success)))
            self.send_header("Connection", "close")
            self._send_auth_cookie_if_needed()
            self.end_headers()
            self.wfile.write(encoded_success)
            self.wfile.flush()
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

        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - Upload Complete</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }}
a, a:hover, a:visited, a:focus, a:active {{ text-decoration:none !important; color:inherit; outline:none; }}
button {{ font-family:inherit; outline:none; }}
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
        return html.replace("</body>", f"{self.get_receiver_session_script()}</body>")

    # ── sender & receiver unified Web UI and API ──
    def send_sender_page(self):
        self.send_unified_web_ui(default_tab="send")

    def send_receive_page(self):
        self.send_unified_web_ui(default_tab="receive")

    def send_unified_web_ui(self, default_tab="send"):
        current_lan_ip = self.server_lan_ip or get_lan_ip()
        has_lan = bool(
            current_lan_ip
            and current_lan_ip not in ("None", "127.0.0.1", "localhost", "")
        )
        pin_str = str(Config.OTP or "----")
        pin_padded = pin_str.ljust(4, "-")
        pin_d0, pin_d1, pin_d2, pin_d3 = pin_padded[0], pin_padded[1], pin_padded[2], pin_padded[3]
        port_val = str(Config.LOCAL_PORT or 6969)
        rec_init_mode = "LAN" if has_lan else "Cloudflare"
        rec_init_url = (
            f"http://{current_lan_ip}:{port_val}"
            if has_lan
            else f"http://localhost:{port_val}"
        )
        rec_init_qr_svg = generate_qr_svg(rec_init_url)

        if default_tab == "receive" and (not sender_sync.is_active or sender_sync.is_send):
            sender_sync.set_active_transfer(
                is_send=False,
                file_paths=[],
                mode_name=rec_init_mode,
                port=int(port_val),
                target_url=rec_init_url,
                pin=pin_str,
                qr_svg=rec_init_qr_svg,
            )
            FileTransferHandler.upload_mode = True
            FileTransferHandler.file_paths = None

        state = sender_sync.get_state()
        if not state.get("target_url") or state.get("is_send"):
            state["rec_initial"] = {
                "mode_name": rec_init_mode,
                "target_url": rec_init_url,
                "qr_svg": rec_init_qr_svg,
                "pin": pin_str,
                "port": int(port_val),
            }

        initial_state_json = json.dumps(state)
        cwd_name = os.path.basename(os.getcwd()) or "workspace"

        html = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - Sender & Receiver</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
a, a:hover, a:visited, a:focus, a:active { text-decoration:none !important; color:inherit; outline:none; }
button { font-family:inherit; outline:none; }
body {
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:#f8fafc; color:#0f172a; min-height:100vh; display:flex; flex-direction:column;
    align-items:center; justify-content:center; padding:24px 16px; -webkit-font-smoothing:antialiased;
}
.container {
    background:#ffffff; border:1px solid #e2e8f0; border-radius:20px; padding:28px 24px;
    box-shadow:0 1px 3px rgba(0,0,0,0.04),0 20px 25px -5px rgba(0,0,0,0.05),0 8px 10px -6px rgba(0,0,0,0.02);
    max-width:480px; width:100%; text-align:center;
}
@media (max-width:520px) { .container { padding:20px 16px; border-radius:16px; } }

.top-brand { display:flex; align-items:center; justify-content:center; gap:8px; margin-bottom:20px; }
.top-brand-icon {
    display:inline-flex; align-items:center; justify-content:center; width:32px; height:32px;
    border-radius:9px; background:#eff6ff; color:#2563eb;
}
.top-brand-name { font-size:19px; font-weight:700; color:#0f172a; letter-spacing:-0.3px; }
.status-badge {
    display:inline-flex; align-items:center; gap:5px; font-size:11px; font-weight:600;
    color:#16a34a; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:9999px;
    padding:2px 8px; margin-left:6px;
}
.status-dot { width:6px; height:6px; border-radius:50%; background:#16a34a; display:inline-block; }

/* Segmented Tab Navigation */
.tab-nav {
    display:flex; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:12px;
    padding:4px; margin-bottom:22px; gap:4px;
}
.tab-btn {
    flex:1; display:inline-flex; align-items:center; justify-content:center; gap:8px;
    padding:10px 14px; border:none; border-radius:9px; font-size:13.5px; font-weight:600;
    color:#64748b; background:transparent; cursor:pointer; text-decoration:none !important;
    transition:all 0.15s ease; outline:none; user-select:none;
}
.tab-btn:hover { color:#0f172a; text-decoration:none !important; }
.tab-btn.active {
    color:#0f172a; background:#ffffff; box-shadow:0 1px 3px rgba(0,0,0,0.08),0 1px 2px rgba(0,0,0,0.04);
    font-weight:700; text-decoration:none !important;
}

.panel { display:none; }
.panel.active { display:block; }

.header { text-align:center; margin-bottom:18px; }
h1 { font-size:20px; font-weight:700; color:#0f172a; margin-bottom:4px; letter-spacing:-0.3px; }
.subtitle { font-size:13px; color:#64748b; font-weight:400; line-height:1.4; }

/* File Drop Area */
.file-drop-area {
    position:relative; border:2px dashed #cbd5e1; border-radius:14px; padding:28px 16px;
    text-align:center; background:#ffffff; cursor:pointer; transition:all 0.15s ease; margin-bottom:16px;
}
.file-drop-area:hover, .file-drop-area.dragover { border-color:#2563eb; background:#eff6ff; }
#file-input { position:absolute; top:0; left:0; width:100%; height:100%; opacity:0; cursor:pointer; }
.drop-icon {
    display:inline-flex; align-items:center; justify-content:center; width:44px; height:44px;
    border-radius:12px; background:#eff6ff; color:#2563eb; margin-bottom:10px;
}
.drop-text { font-size:14px; font-weight:600; color:#0f172a; margin-bottom:3px; }
.drop-hint { font-size:12px; color:#64748b; }

/* File Preview List */
.file-preview-area { margin-bottom:16px; text-align:left; }
.file-section-header, .section-top-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
.file-section-title, .section-title { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.6px; color:#64748b; }
.file-count-badge { font-size:11px; font-weight:600; color:#2563eb; background:#eff6ff; padding:2px 8px; border-radius:12px; }
.clear-btn { background:none; border:none; color:#dc2626; font-size:12px; font-weight:500; cursor:pointer; padding:2px 6px; border-radius:4px; text-decoration:none !important; }
.clear-btn:hover { background:#fef2f2; }
.file-list { list-style:none; border:1px solid #e2e8f0; border-radius:10px; overflow:hidden; background:#ffffff; max-height:160px; overflow-y:auto; }
.file-list li { border-bottom:1px solid #f1f5f9; display:flex; align-items:center; justify-content:space-between; padding:9px 12px; min-height:42px; gap:8px; font-size:13px; }
.file-list li:last-child { border-bottom:none; }
.file-item-left { display:flex; align-items:center; gap:8px; overflow:hidden; min-width:0; flex:1; text-align:left; }
.file-icon { color:#64748b; flex-shrink:0; }
.file-name { font-size:13px; font-weight:500; color:#0f172a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.file-meta { display:flex; align-items:center; gap:8px; flex-shrink:0; }
.file-size { font-size:11px; color:#64748b; background:#f1f5f9; padding:2px 6px; border-radius:6px; font-weight:500; white-space:nowrap; }
.remove-btn { background:none; border:none; color:#94a3b8; font-size:16px; cursor:pointer; padding:0 4px; line-height:1; text-decoration:none !important; }
.remove-btn:hover { color:#dc2626; }
.file-summary { font-size:12px; font-weight:600; color:#2563eb; margin-top:8px; text-align:center; }

/* Section Header & Inline Port */
.mode-section, .section-box { margin-bottom:16px; text-align:left; }
.port-bar-wrap { display:inline-flex; align-items:center; gap:6px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:8px; padding:2px 4px 2px 8px; }
.port-bar-label { font-size:11px; font-weight:600; color:#64748b; }
.port-bar-input, .port-inline-input {
    width:52px; padding:3px 4px; background:#ffffff; border:1px solid #cbd5e1;
    border-radius:6px; font-size:11.5px; font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
    font-weight:600; color:#0f172a; text-align:center; outline:none; transition:border 0.15s;
}
.port-bar-input:focus, .port-inline-input:focus { border-color:#2563eb; }
.port-bar-btn, .port-inline-btn {
    padding:3px 8px; background:#2563eb; color:#ffffff; border:none;
    border-radius:6px; font-size:11px; font-weight:600; cursor:pointer; text-decoration:none !important;
    transition:background 0.15s;
}
.port-bar-btn:hover, .port-inline-btn:hover { background:#1d4ed8; }

/* Mode Selection Grid */
.mode-grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:6px; margin-top:8px; }
.mode-btn {
    background:#ffffff; border:1.5px solid #e2e8f0; border-radius:10px; padding:10px 4px;
    text-align:center; cursor:pointer; transition:all 0.15s ease; color:#475569; user-select:none;
    display:flex; flex-direction:column; align-items:center; justify-content:center; text-decoration:none !important;
}
.mode-btn:hover { border-color:#cbd5e1; background:#f8fafc; color:#0f172a; }
.mode-btn.active, .mode-btn.selected {
    border-color:#2563eb; background:#eff6ff; color:#2563eb; box-shadow:0 1px 2px rgba(37,99,235,0.1);
}
.mode-btn-title { font-size:12px; font-weight:700; display:block; color:#0f172a; line-height:1.2; }
.mode-btn-desc { font-size:10px; color:#64748b; display:block; margin-top:2px; font-weight:500; }
.mode-btn.active .mode-btn-title, .mode-btn.selected .mode-btn-title { color:#1d4ed8; }
.mode-btn.active .mode-btn-desc, .mode-btn.selected .mode-btn-desc { color:#3b82f6; }
.mode-btn input[type="radio"] { display:none; }

.notice-box {
    margin-top:8px; font-size:12px; color:#1e40af; background:#eff6ff;
    border:1px solid #bfdbfe; border-radius:8px; padding:8px 12px; line-height:1.4;
}

/* Connection / QR Card */
.qr-card {
    background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:20px 18px;
    margin:16px 0; text-align:center; position:relative;
}
.qr-frame {
    display:inline-flex; align-items:center; justify-content:center;
    background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:14px;
    box-shadow:0 2px 6px rgba(0,0,0,0.04);
}
.qr-wrapper {
    display:flex; align-items:center; justify-content:center; max-width:190px; max-height:190px;
}
.qr-wrapper svg { width:100%; height:100%; display:block; border-radius:6px; }
.scan-hint { font-size:12.5px; color:#64748b; margin-top:10px; margin-bottom:2px; font-weight:500; }

.loading-overlay {
    position:absolute; top:0; left:0; width:100%; height:100%; background:rgba(255,255,255,0.92);
    border-radius:16px; display:flex; flex-direction:column;
    align-items:center; justify-content:center; gap:8px; z-index:10;
}
.spinner {
    width:24px; height:24px; border:2.5px solid #cbd5e1; border-top-color:#2563eb;
    border-radius:50%; animation:spin 0.75s linear infinite; display:inline-block; flex-shrink:0;
}
@keyframes spin { to { transform:rotate(360deg); } }
.loading-text { font-size:12px; color:#64748b; font-weight:500; }

/* Prominent Access Code Display */
.access-code-card {
    background:#ffffff; border:1px solid #e2e8f0; border-radius:14px;
    padding:14px 16px; margin:14px 0 10px 0; box-shadow:0 1px 3px rgba(0,0,0,0.03);
    text-align:center;
}
.access-code-header {
    display:flex; justify-content:space-between; align-items:center;
    margin-bottom:10px; padding:0 4px;
}
.access-code-title {
    display:flex; align-items:center; gap:5px; font-size:11px;
    font-weight:700; text-transform:uppercase; letter-spacing:0.8px; color:#64748b;
}
.access-code-sub { font-size:11px; color:#94a3b8; font-weight:500; }
.digit-boxes { display:flex; justify-content:center; align-items:center; gap:8px; }
.digit-box {
    width:44px; height:52px; background:#f8fafc; border:1.5px solid #cbd5e1;
    border-radius:10px; font-size:24px; font-weight:800; color:#0f172a;
    display:flex; align-items:center; justify-content:center;
    font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
    box-shadow:inset 0 1px 2px rgba(0,0,0,0.04); transition:all 0.15s ease;
}
.pin-hidden { display:none !important; }

/* URL Row */
.url-box, .url-badge {
    display:flex; align-items:center; justify-content:space-between; background:#ffffff;
    border:1px solid #e2e8f0; border-radius:10px; padding:6px 6px 6px 12px; width:100%; box-sizing:border-box; gap:8px; margin-top:10px;
}
.url-left { display:flex; align-items:center; gap:8px; overflow:hidden; min-width:0; flex:1; }
.url-icon { color:#64748b; flex-shrink:0; }
.url-text {
    font-size:12px; font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
    color:#2563eb; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:left; font-weight:600;
}
.copy-btn {
    background:#eff6ff; color:#2563eb; border:1px solid #bfdbfe; border-radius:7px; padding:6px 12px;
    font-size:11.5px; font-weight:600; cursor:pointer; text-decoration:none !important; transition:all 0.15s; flex-shrink:0;
}
.copy-btn:hover { background:#dbeafe; border-color:#93c5fd; }

/* Progress Container */
.progress-container, .progress-card {
    background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:14px; margin-top:14px; text-align:left;
}
.progress-status, .progress-meta { font-size:13px; font-weight:600; color:#0f172a; margin-bottom:8px; display:flex; align-items:center; justify-content:space-between; gap:8px; }
.progress-label { font-weight:600; color:#0f172a; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:240px; }
.progress-pct { font-weight:700; color:#2563eb; font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; }
.progress-bar-bg { width:100%; height:6px; background:#e2e8f0; border-radius:3px; overflow:hidden; }
.progress-bar-fill { height:100%; width:0%; background:#2563eb; border-radius:3px; transition:width 0.15s ease; }
.progress-info { display:flex; justify-content:space-between; margin-top:8px; font-size:12px; color:#64748b; font-weight:500; }

/* Incoming Transfers */
.incoming-section { text-align:left; margin-bottom:16px; margin-top:14px; }
.cwd-badge { font-size:11px; color:#64748b; background:#f1f5f9; border:1px solid #e2e8f0; padding:2px 8px; border-radius:6px; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.empty-state {
    background:#ffffff; border:1px dashed #cbd5e1; border-radius:12px; padding:20px;
    text-align:center; font-size:12.5px; color:#64748b; display:flex; align-items:center; justify-content:center; gap:8px;
}

/* Action Buttons */
.submit-button {
    display:flex; align-items:center; justify-content:center; gap:8px; width:100%; padding:13px 20px;
    background:#2563eb; color:#ffffff; border:none; border-radius:12px; font-size:14.5px; font-weight:600;
    cursor:pointer; text-decoration:none !important; transition:all 0.15s; opacity:0.4; pointer-events:none; margin-top:14px;
}
.submit-button.enabled { opacity:1; pointer-events:auto; box-shadow:0 1px 2px rgba(37,99,235,0.2); }
.submit-button.enabled:hover { background:#1d4ed8; }
.stop-button {
    display:flex; align-items:center; justify-content:center; gap:8px; width:100%; padding:11px 20px;
    background:#ffffff; color:#dc2626; border:1px solid #fecaca; border-radius:12px;
    font-size:13px; font-weight:600; cursor:pointer; text-decoration:none !important; transition:all 0.15s; margin-top:16px;
}
.stop-button:hover { background:#fef2f2; border-color:#fca5a5; }
.footer { text-align:center; margin-top:22px; font-size:12px; color:#94a3b8; font-weight:500; }
</style>
</head>
<body>
<div class="container">
  <div class="top-brand">
    <div class="top-brand-icon">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
    </div>
    <span class="top-brand-name">qrtunnel</span>
    <span class="status-badge"><span class="status-dot"></span>Ready</span>
  </div>

  <!-- Segmented Tab Navigation -->
  <div class="tab-nav">
    <a href="/sender" class="tab-btn active" id="tab-btn-send" onclick="switchMainTab('send'); return false;">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
      Send Files
    </a>
    <a href="/receive" class="tab-btn" id="tab-btn-receive" onclick="switchMainTab('receive'); return false;">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Receive Files
    </a>
  </div>

  <!-- PANEL 1: SEND FILES -->
  <div id="panel-send" class="panel active">
    <div class="header">
      <h1 id="page-title">Send Files</h1>
      <p class="subtitle" id="page-subtitle">Select files to share via QR code or link</p>
    </div>

    <!-- SELECTION VIEW -->
    <div id="selection-view">
      <div class="file-drop-area" id="drop-area">
        <input type="file" id="file-input" multiple>
        <div class="drop-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        </div>
        <p class="drop-text" id="drop-text">Click or drag files here</p>
        <p class="drop-hint">Select one or multiple files to send</p>
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
        <div class="section-top-bar">
          <span class="section-title">Tunnel Mode</span>
          <div class="port-bar-wrap">
            <span class="port-bar-label">Port:</span>
            <input type="number" id="port-input" min="1" max="65535" value="""" + port_val + """" class="port-bar-input" />
            <button type="button" id="apply-port-btn" class="port-bar-btn">Set</button>
          </div>
        </div>
        <div class="mode-grid">
          <label class="mode-btn selected" id="lbl-lan">
            <input type="radio" name="mode" value="LAN" checked>
            <span class="mode-btn-title">LAN</span>
            <span class="mode-btn-desc">Local Wi-Fi</span>
          </label>
          <label class="mode-btn" id="lbl-cf">
            <input type="radio" name="mode" value="Cloudflare">
            <span class="mode-btn-title">Cloudflare</span>
            <span class="mode-btn-desc">Public Tunnel</span>
          </label>
          <label class="mode-btn" id="lbl-ssh">
            <input type="radio" name="mode" value="SSH">
            <span class="mode-btn-title">SSH Tunnel</span>
            <span class="mode-btn-desc">Port 22/443</span>
          </label>
          <label class="mode-btn" id="lbl-ngrok">
            <input type="radio" name="mode" value="Ngrok">
            <span class="mode-btn-title">Ngrok</span>
            <span class="mode-btn-desc">Secure Link</span>
          </label>
        </div>
        <div id="lan-mode-notice" class="notice-box" style="display:none;">Not in same LAN, switching to the other connection...</div>
        <div id="port-feedback" style="display:none;font-size:12px;margin-top:6px;border-radius:6px;padding:6px 10px;"></div>
      </div>

      <button type="button" id="submit-btn" class="submit-button">Share Files</button>
    </div>

    <!-- ACTIVE VIEW -->
    <div id="active-view" style="display:none;">
      <div id="lan-switch-notice" class="notice-box" style="display:none;margin-bottom:14px;text-align:center;">
        Not in same LAN, switching to the other connection...
      </div>
      <div class="qr-card">
        <div class="qr-frame">
          <div class="qr-wrapper" id="qr-wrapper"></div>
        </div>
        <p class="scan-hint">Scan with phone camera to download files</p>

        <!-- DEDICATED PROMINENT ACCESS CODE CARD -->
        <div class="access-code-card">
          <div class="access-code-header">
            <div class="access-code-title">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <span>ACCESS CODE</span>
            </div>
            <span class="access-code-sub">Enter on receiver device</span>
          </div>
          <div class="digit-boxes" id="pin-badge-wrap">
            <div class="digit-box" id="send-d-0">-</div>
            <div class="digit-box" id="send-d-1">-</div>
            <div class="digit-box" id="send-d-2">-</div>
            <div class="digit-box" id="send-d-3">-</div>
            <span id="pin-val" class="pin-hidden">----</span>
          </div>
        </div>

        <!-- URL ROW -->
        <div class="url-box url-badge">
          <div class="url-left">
            <svg class="url-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
            <span class="url-text" id="target-url-text">http://...</span>
          </div>
          <button type="button" class="copy-btn" id="copy-btn">Copy Link</button>
        </div>
      </div>

      <div class="file-preview-area" id="active-files-area">
        <div class="section-top-bar">
          <span class="section-title">Files Being Shared</span>
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
  </div>

  <!-- PANEL 2: RECEIVE FILES -->
  <div id="panel-receive" class="panel">
    <div class="header">
      <h1>Receive Files</h1>
      <p class="subtitle">Select connection mode to show QR code for upload</p>
    </div>

    <div class="mode-section">
      <div class="section-top-bar">
        <span class="section-title">Connection Mode</span>
        <div class="port-bar-wrap">
          <span class="port-bar-label">Port:</span>
          <input type="number" id="rec-port-input" min="1" max="65535" value="""" + port_val + """" class="port-bar-input" />
          <button type="button" id="port-apply-btn" class="port-bar-btn">Set</button>
        </div>
      </div>
      <div class="mode-grid">
        <button type="button" class="mode-btn active" data-mode="LAN">
          <span class="mode-btn-title">LAN</span>
          <span class="mode-btn-desc">Local Wi-Fi</span>
        </button>
        <button type="button" class="mode-btn" data-mode="Cloudflare">
          <span class="mode-btn-title">Cloudflare</span>
          <span class="mode-btn-desc">Public Tunnel</span>
        </button>
        <button type="button" class="mode-btn" data-mode="SSH">
          <span class="mode-btn-title">SSH Tunnel</span>
          <span class="mode-btn-desc">Port 22/443</span>
        </button>
        <button type="button" class="mode-btn" data-mode="Ngrok">
          <span class="mode-btn-title">Ngrok</span>
          <span class="mode-btn-desc">Secure Link</span>
        </button>
      </div>
      <div id="rec-notice-box" class="notice-box" style="display:none;"></div>
    </div>

    <!-- QR CARD -->
    <div class="qr-card">
      <div id="rec-loading-spinner" class="loading-overlay" style="display:none;">
        <div class="spinner"></div>
        <span id="rec-loading-text" class="loading-text">Connecting...</span>
      </div>
      <div class="qr-frame">
        <div class="qr-wrapper" id="rec-qr-wrapper">""" + rec_init_qr_svg + """</div>
      </div>
      <p class="scan-hint">Scan with phone camera to open upload page</p>

      <!-- DEDICATED PROMINENT ACCESS CODE CARD -->
      <div class="access-code-card">
        <div class="access-code-header">
          <div class="access-code-title">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            <span>ACCESS CODE</span>
          </div>
          <span class="access-code-sub">Enter on phone after scanning</span>
        </div>
        <div class="digit-boxes">
          <div class="digit-box" id="rec-d-0">""" + pin_d0 + """</div>
          <div class="digit-box" id="rec-d-1">""" + pin_d1 + """</div>
          <div class="digit-box" id="rec-d-2">""" + pin_d2 + """</div>
          <div class="digit-box" id="rec-d-3">""" + pin_d3 + """</div>
          <span id="pin-display" class="pin-hidden">""" + pin_str + """</span>
        </div>
      </div>

      <!-- URL ROW -->
      <div class="url-box">
        <div class="url-left">
          <svg class="url-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
          <span class="url-text" id="rec-target-url-text">""" + rec_init_url + """</span>
        </div>
        <button type="button" class="copy-btn" id="rec-copy-btn">Copy Link</button>
      </div>
    </div>

    <!-- INCOMING SECTION -->
    <div class="incoming-section">
      <div class="section-top-bar">
        <span class="section-title">Incoming Transfers</span>
        <span class="cwd-badge" title="Save directory">📁 """ + cwd_name + """</span>
      </div>
      <div id="rec-progress-card" class="progress-card" style="display:none;">
        <div class="progress-meta">
          <span id="rec-progress-label" class="progress-label">Uploading...</span>
          <span id="rec-progress-pct" class="progress-pct">0%</span>
        </div>
        <div class="progress-bar-bg"><div id="rec-progress-bar-fill" class="progress-bar-fill"></div></div>
      </div>
      <ul class="file-list" id="received-list"></ul>
      <div id="empty-state" class="empty-state">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        <span>No files received yet. Waiting for uploads...</span>
      </div>
    </div>

    <button type="button" id="close-session-btn" class="stop-button">Close Session</button>
  </div>

  <p class="footer">qrtunnel</p>
</div>

<script>
let activeTab = "send";
function switchMainTab(tab) {
    activeTab = tab;
    const isSend = tab === 'send';
    document.getElementById('tab-btn-send').classList.toggle('active', isSend);
    document.getElementById('tab-btn-receive').classList.toggle('active', !isSend);
    document.getElementById('panel-send').classList.toggle('active', isSend);
    document.getElementById('panel-receive').classList.toggle('active', !isSend);
    window.location.hash = '#' + tab;
    if (!isSend) {
        if (!currentRecState || currentRecState.is_send !== false) {
            switchRecMode(currentRecMode, currentRecPort);
        }
    }
}

function setPinDigits(pinStr, prefix) {
    const s = String(pinStr || '----').padEnd(4, '-');
    for (let i = 0; i < 4; i++) {
        const el = document.getElementById(prefix + '-d-' + i);
        if (el) el.textContent = s[i] || '-';
    }
}

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

const portInput = document.getElementById('port-input');
const portDisplay = document.getElementById('port-display');
const applyPortBtn = document.getElementById('apply-port-btn');
const portFeedback = document.getElementById('port-feedback');
const activePortVal = document.getElementById('active-port-val');
const lanSwitchNotice = document.getElementById('lan-switch-notice');
const lanModeNotice = document.getElementById('lan-mode-notice');

if (typeof __INITIAL_STATE__ !== 'undefined' && __INITIAL_STATE__) {
    if (__INITIAL_STATE__.port) {
        if (portInput) portInput.value = __INITIAL_STATE__.port;
        if (portDisplay) portDisplay.textContent = __INITIAL_STATE__.port;
        if (activePortVal) activePortVal.textContent = __INITIAL_STATE__.port;
    }
}

if (applyPortBtn && portInput) {
    applyPortBtn.addEventListener('click', () => {
        const newPort = parseInt(portInput.value, 10);
        if (!newPort || newPort < 1 || newPort > 65535) {
            portFeedback.style.display = 'block';
            portFeedback.style.background = '#fef2f2';
            portFeedback.style.border = '1px solid #fecaca';
            portFeedback.style.color = '#dc2626';
            portFeedback.textContent = 'Please enter a valid port number (1–65535).';
            return;
        }
        applyPortBtn.textContent = 'Updating...';
        applyPortBtn.style.pointerEvents = 'none';

        fetch('/api/sender/port', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ port: newPort })
        })
        .then(r => r.json())
        .then(data => {
            applyPortBtn.textContent = 'Apply';
            applyPortBtn.style.pointerEvents = 'auto';
            if (data.success) {
                portFeedback.style.display = 'block';
                portFeedback.style.background = '#f0fdf4';
                portFeedback.style.border = '1px solid #bbf7d0';
                portFeedback.style.color = '#15803d';
                portFeedback.textContent = `✓ Port set to ${data.port}`;
                if (portDisplay) portDisplay.textContent = data.port;
                if (activePortVal) activePortVal.textContent = data.port;
                if (recPortInput) recPortInput.value = data.port;
                currentRecPort = data.port;
                if (typeof initialState !== 'undefined' && initialState) initialState.port = data.port;
                setTimeout(() => {
                    if (portFeedback.textContent.includes('✓')) {
                        portFeedback.style.display = 'none';
                    }
                }, 3500);
            } else {
                portFeedback.style.display = 'block';
                portFeedback.style.background = '#fef2f2';
                portFeedback.style.border = '1px solid #fecaca';
                portFeedback.style.color = '#dc2626';
                portFeedback.textContent = data.error || 'Failed to update port.';
            }
        })
        .catch(() => {
            applyPortBtn.textContent = 'Apply';
            applyPortBtn.style.pointerEvents = 'auto';
            portFeedback.style.display = 'block';
            portFeedback.style.background = '#fef2f2';
            portFeedback.style.border = '1px solid #fecaca';
            portFeedback.style.color = '#dc2626';
            portFeedback.textContent = 'Error contacting server to update port.';
        });
    });

    portInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            applyPortBtn.click();
        }
    });
}

document.querySelectorAll('input[name="mode"]').forEach(radio => {
    radio.addEventListener('change', () => {
        document.querySelectorAll('.mode-btn').forEach(l => {
            if (l.tagName.toLowerCase() === 'label') l.classList.remove('selected');
        });
        radio.closest('label').classList.add('selected');
        if (radio.value === 'LAN') {
            const hasLan = initialState.lan_ip && initialState.lan_ip !== '127.0.0.1' && initialState.lan_ip !== 'localhost' && initialState.lan_ip !== 'None';
            if (!hasLan) {
                if (lanModeNotice) {
                    lanModeNotice.style.display = 'block';
                    lanModeNotice.textContent = 'Not in same LAN, switching to the other connection...';
                }
                setTimeout(() => {
                    const cfRadio = document.querySelector('input[name="mode"][value="Cloudflare"]');
                    if (cfRadio) {
                        cfRadio.checked = true;
                        document.querySelectorAll('.mode-btn').forEach(l => {
                            if (l.tagName.toLowerCase() === 'label') l.classList.remove('selected');
                        });
                        const lblCf = document.getElementById('lbl-cf');
                        if (lblCf) lblCf.classList.add('selected');
                    }
                }, 800);
            } else if (lanModeNotice) {
                lanModeNotice.style.display = 'none';
            }
        } else if (lanModeNotice) {
            lanModeNotice.style.display = 'none';
        }
    });
});

submitBtn.addEventListener('click', () => {
    if (!selectedFiles.length) return;
    submitBtn.classList.remove('enabled');
    submitBtn.textContent = 'Preparing Transfer...';

    const selectedMode = document.querySelector('input[name="mode"]:checked').value;
    const chosenPort = (portInput && parseInt(portInput.value, 10)) || (initialState && initialState.port) || 6969;
    const formData = new FormData();
    selectedFiles.forEach(f => formData.append('file', f));

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/sender/share?mode=${encodeURIComponent(selectedMode)}&port=${chosenPort}`, true);

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
    setPinDigits(data.pin, 'send');
    targetUrlText.textContent = data.target_url || '';
    if (data.port && activePortVal) {
        activePortVal.textContent = data.port;
    }
    if (data.notice && lanSwitchNotice) {
        lanSwitchNotice.textContent = data.notice;
        lanSwitchNotice.style.display = 'block';
    } else if (lanSwitchNotice) {
        lanSwitchNotice.style.display = 'none';
    }

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

// ── RECEIVER VIEW LOGIC ──
let currentRecMode = "LAN";
let currentRecPort = (typeof __INITIAL_STATE__ !== 'undefined' && __INITIAL_STATE__ && __INITIAL_STATE__.port) || 6969;
let currentRecUrl = "";
let currentRecState = null;

const recQrWrapper = document.getElementById('rec-qr-wrapper');
const pinDisplay = document.getElementById('pin-display');
const recTargetUrlText = document.getElementById('rec-target-url-text');
const recCopyBtn = document.getElementById('rec-copy-btn');
const recPortInput = document.getElementById('rec-port-input');
const portApplyBtn = document.getElementById('port-apply-btn');
const recNoticeBox = document.getElementById('rec-notice-box');
const recLoadingSpinner = document.getElementById('rec-loading-spinner');
const recLoadingText = document.getElementById('rec-loading-text');
const receivedList = document.getElementById('received-list');
const emptyState = document.getElementById('empty-state');
const recProgressCard = document.getElementById('rec-progress-card');
const recProgressBarFill = document.getElementById('rec-progress-bar-fill');
const recProgressPct = document.getElementById('rec-progress-pct');
const recProgressLabel = document.getElementById('rec-progress-label');
const closeSessionBtn = document.getElementById('close-session-btn');

function updateRecUi(data) {
    if (!data) return;
    currentRecState = data;
    if (data.mode_name) {
        currentRecMode = data.mode_name;
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-mode') === data.mode_name);
        });
    }
    if (data.port) {
        currentRecPort = data.port;
        if (recPortInput) recPortInput.value = data.port;
    }
    if (data.pin) {
        pinDisplay.textContent = data.pin;
        setPinDigits(data.pin, 'rec');
    }
    if (data.target_url) {
        currentRecUrl = data.target_url;
        recTargetUrlText.textContent = data.target_url;
    }
    if (data.qr_svg) {
        recQrWrapper.innerHTML = data.qr_svg;
    }
    if (data.notice) {
        recNoticeBox.textContent = data.notice;
        recNoticeBox.style.display = 'block';
    } else {
        recNoticeBox.style.display = 'none';
    }
    if (data.received_files && Array.isArray(data.received_files)) {
        renderReceivedFiles(data.received_files);
    }
}

function renderReceivedFiles(files) {
    receivedList.innerHTML = '';
    if (files.length === 0) {
        emptyState.style.display = 'flex';
    } else {
        emptyState.style.display = 'none';
        files.forEach(f => {
            const li = document.createElement('li');
            li.innerHTML = `
              <div class="file-item-left">
                <svg class="file-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                <span class="file-name" title="${f.name}">${f.name}</span>
              </div>
              <div class="file-meta">
                <span class="file-size">${formatBytes(f.size)}</span>
              </div>`;
            receivedList.appendChild(li);
        });
    }
}

function addReceivedFile(f) {
    emptyState.style.display = 'none';
    const li = document.createElement('li');
    li.innerHTML = `
      <div class="file-item-left">
        <svg class="file-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
        <span class="file-name" title="${f.name}">${f.name}</span>
      </div>
      <div class="file-meta">
        <span class="file-size">${formatBytes(f.size)}</span>
      </div>`;
    receivedList.prepend(li);
}

function switchRecMode(newMode, portVal) {
    recLoadingText.textContent = `Establishing ${newMode} tunnel...`;
    recLoadingSpinner.style.display = 'flex';
    const port = portVal || currentRecPort;

    fetch(`/api/receiver/mode?mode=${encodeURIComponent(newMode)}&port=${port}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                updateRecUi(data);
            } else {
                alert('Could not switch mode: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(() => {
            alert('Network error switching connection mode');
        })
        .finally(() => {
            recLoadingSpinner.style.display = 'none';
        });
}

document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const mode = btn.getAttribute('data-mode');
        switchRecMode(mode, currentRecPort);
    });
});

if (portApplyBtn && recPortInput) {
    portApplyBtn.addEventListener('click', () => {
        const val = parseInt(recPortInput.value, 10);
        if (!val || val < 1 || val > 65535) {
            alert('Please enter a valid port between 1 and 65535');
            return;
        }
        switchRecMode(currentRecMode, val);
    });
    recPortInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            portApplyBtn.click();
        }
    });
}

recCopyBtn.addEventListener('click', () => {
    if (!currentRecUrl) return;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(currentRecUrl).then(() => {
            recCopyBtn.textContent = 'Copied!';
            setTimeout(() => { recCopyBtn.textContent = 'Copy Link'; }, 1500);
        });
    }
});

function showSessionEnded() {
    document.body.innerHTML = `
      <div class="container" style="text-align:center;padding:40px 24px;">
        <div class="badge-icon" style="background:#f1f5f9;color:#64748b;margin:0 auto 14px;">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
        </div>
        <h1 style="color:#0f172a;margin-bottom:6px;font-size:20px;font-weight:700;">Session Ended</h1>
        <p class="subtitle">qrtunnel has stopped. You can safely close this window.</p>
      </div>`;
}

stopBtn.addEventListener('click', () => {
    fetch('/api/sender/stop', { method: 'POST' }).finally(() => {
        showSessionEnded();
    });
});

closeSessionBtn.addEventListener('click', () => {
    fetch('/api/sender/close', { method: 'POST' }).finally(() => {
        showSessionEnded();
    });
});

function closeNotification() {
    navigator.sendBeacon('/api/sender/close');
}
window.addEventListener('beforeunload', closeNotification);
window.addEventListener('pagehide', closeNotification);

setInterval(() => {
    fetch('/api/sender/heartbeat', { method: 'POST', keepalive: true }).catch(() => {});
}, 1500);

// Initialize with current server state
const initialState = __INITIAL_STATE__;
if (initialState) {
    if (initialState.is_active && initialState.is_send !== false) {
        switchToActiveView(initialState);
    }
    if (initialState.is_send === false) {
        updateRecUi(initialState);
    } else if (initialState.rec_initial) {
        updateRecUi(initialState.rec_initial);
    }
}

const requestedTab = "__DEFAULT_TAB__";
const hash = window.location.hash.toLowerCase();
if (hash === '#receive' || requestedTab === 'receive') {
    switchMainTab('receive');
} else {
    switchMainTab('send');
}

const evtSource = new EventSource('/api/sender/events');

evtSource.addEventListener('state', (e) => {
    try {
        const state = JSON.parse(e.data);
        if (state.is_send !== false && state.is_active) {
            switchToActiveView(state);
        } else if (state.is_send === false) {
            updateRecUi(state);
        }
    } catch (err) {}
});

evtSource.addEventListener('progress', (e) => {
    try {
        const data = JSON.parse(e.data);
        const pct = data.pct || 0;
        // Update send progress
        progressBar.style.width = pct + '%';
        progressPct.textContent = pct + '%';
        progressSpeed.textContent = formatBytes(data.speed || 0) + '/s';
        progressStats.textContent = `${formatBytes(data.transferred || 0)} / ${formatBytes(data.total || 0)}`;

        if (data.status === 'completed') {
            progressSpinner.style.display = 'none';
            progressStatusText.textContent = '✓ Transfer Complete!';
            progressBar.style.background = '#15803d';
        } else {
            progressSpinner.style.display = 'inline-block';
            progressStatusText.textContent = data.label ? `Transferring ${data.label}...` : 'Transferring...';
            progressBar.style.background = '#2563eb';
        }

        // Update receive progress
        if (data.status === 'transferring') {
            recProgressCard.style.display = 'block';
            recProgressLabel.textContent = data.label || 'Uploading...';
            recProgressPct.textContent = pct + '%';
            recProgressBarFill.style.width = pct + '%';
        } else if (data.status === 'completed') {
            recProgressPct.textContent = '100%';
            recProgressBarFill.style.width = '100%';
            setTimeout(() => { recProgressCard.style.display = 'none'; }, 2000);
        }
    } catch (err) {}
});

evtSource.addEventListener('received', (e) => {
    try {
        const data = JSON.parse(e.data);
        addReceivedFile(data);
    } catch (err) {}
});

evtSource.addEventListener('close', () => {
    showSessionEnded();
});
</script>
</body></html>""".replace("__INITIAL_STATE__", initial_state_json).replace("__DEFAULT_TAB__", default_tab)

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode("utf-8"))))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def handle_receiver_mode(self):
        try:
            parsed_query = parse_qs(urlparse(self.path).query)
            mode_name = "LAN"
            if "mode" in parsed_query:
                mode_name = parsed_query["mode"][0]
            port = Config.LOCAL_PORT
            if "port" in parsed_query:
                try:
                    p = int(parsed_query["port"][0])
                    if 1 <= p <= 65535:
                        port = p
                except (ValueError, TypeError):
                    pass

            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if "mode" in payload:
                        mode_name = payload["mode"]
                    if "port" in payload:
                        p = int(payload["port"])
                        if 1 <= p <= 65535:
                            port = p
                except Exception:
                    pass

            if port != Config.LOCAL_PORT:
                try:
                    new_server = ThreadingHTTPServer(("0.0.0.0", port), FileTransferHandler)
                    new_thread = threading.Thread(
                        target=new_server.serve_forever, daemon=True
                    )
                    new_thread.start()
                    sender_sync.register_server(new_server)
                    Config.LOCAL_PORT = port
                    sender_sync.port = port
                except Exception as pe:
                    print(f"{WRN} Could not rebind to port {port}: {pe}")

            from .tunnels import TunnelManager

            current_lan_ip = self.server_lan_ip or get_lan_ip()
            has_lan = bool(
                current_lan_ip
                and current_lan_ip not in ("None", "127.0.0.1", "localhost", "")
            )

            lan_notice = None
            if mode_name == "LAN" and not has_lan:
                print(
                    f"{INFO} Not in same LAN (no local network detected), "
                    "switching to Cloudflare tunnel..."
                )
                mode_name = "Cloudflare"
                lan_notice = "Not in same LAN, switching to Cloudflare tunnel..."

            lan_url = (
                f"http://{current_lan_ip}:{Config.LOCAL_PORT}"
                if has_lan
                else f"http://localhost:{Config.LOCAL_PORT}"
            )
            FileTransferHandler.lan_url = lan_url
            target_url = lan_url

            if sender_sync.tunnel_manager:
                try:
                    sender_sync.tunnel_manager.stop()
                except Exception:
                    pass
                sender_sync.tunnel_manager = None

            if mode_name != "LAN":
                tunnel_backend = (
                    mode_name.lower()
                    if mode_name in ("Cloudflare", "Ngrok", "SSH")
                    else None
                )
                noauth = mode_name != "Ngrok"
                tm = TunnelManager(
                    Config.LOCAL_PORT,
                    noauth=noauth,
                    lan_only=False,
                    lan_ip=current_lan_ip,
                    tunnel_backend=tunnel_backend,
                )
                tm.start()
                if tm and (tm.public_url or tm.lan_url):
                    sender_sync.tunnel_manager = tm
                    if tm.public_url:
                        target_url = tm.public_url
                        FileTransferHandler.public_url = tm.public_url
                    else:
                        target_url = tm.lan_url
                        if not lan_notice:
                            lan_notice = f"Could not establish {mode_name} tunnel, running on LAN."
                        mode_name = "LAN"

            FileTransferHandler.upload_mode = True
            FileTransferHandler.file_paths = None
            qr_svg = generate_qr_svg(target_url)

            sender_sync.set_active_transfer(
                is_send=False,
                file_paths=[],
                mode_name=mode_name,
                port=Config.LOCAL_PORT,
                target_url=target_url,
                pin=Config.OTP,
                qr_svg=qr_svg,
            )

            resp_data = {
                "success": True,
                "mode_name": mode_name,
                "target_url": target_url,
                "qr_svg": qr_svg,
                "pin": Config.OTP,
                "port": Config.LOCAL_PORT,
                "notice": lan_notice,
                "is_send": False,
                "received_files": sender_sync.received_files,
            }
            encoded = json.dumps(resp_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            self.wfile.flush()
        except Exception as e:
            print(f"{ERR} Error in handle_receiver_mode: {e}")
            err_resp = json.dumps({"success": False, "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_resp)))
            self.end_headers()
            self.wfile.write(err_resp)
            self.wfile.flush()

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

    def handle_session_status(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        closed = sender_sync.is_closed()
        status_data = json.dumps({"closed": closed, "status": sender_sync.status}).encode("utf-8")
        self.send_header("Content-Length", str(len(status_data)))
        self.end_headers()
        self.wfile.write(status_data)

    def handle_receiver_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        initial_closed = sender_sync.is_closed()
        try:
            initial_msg = (
                f"event: status\ndata: {json.dumps({'closed': initial_closed})}\n\n"
            ).encode()
            self.wfile.write(initial_msg)
            self.wfile.flush()
            if initial_closed:
                close_msg = b'event: close\ndata: {"closed": true}\n\n'
                self.wfile.write(close_msg)
                self.wfile.flush()
                return
        except Exception:
            return

        q = sender_sync.subscribe()
        try:
            while not sender_sync.is_closed():
                try:
                    msg = q.get(timeout=1.0)
                    if "event: close" in msg:
                        self.wfile.write(msg.encode("utf-8"))
                        self.wfile.flush()
                        break
                    elif "event: progress" in msg:
                        self.wfile.write(msg.encode("utf-8"))
                        self.wfile.flush()
                except queue.Empty:
                    try:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except Exception:
                        break
            try:
                self.wfile.write(b'event: close\ndata: {"closed": true}\n\n')
                self.wfile.flush()
            except Exception:
                pass
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            sender_sync.unsubscribe(q)

    def handle_sender_port(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body)
                new_port = int(data.get("port", 0))
            except Exception:
                from urllib.parse import parse_qs

                params = parse_qs(body)
                new_port = int(params.get("port", [0])[0])

            if new_port < 1 or new_port > 65535:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                err_resp = json.dumps(
                    {"success": False, "error": "Invalid port number. Must be between 1 and 65535."}
                ).encode("utf-8")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
                return

            if new_port == Config.LOCAL_PORT:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                ok_resp = json.dumps(
                    {
                        "success": True,
                        "port": new_port,
                        "redirect_url": f"http://127.0.0.1:{new_port}/sender",
                    }
                ).encode("utf-8")
                self.send_header("Content-Length", str(len(ok_resp)))
                self.end_headers()
                self.wfile.write(ok_resp)
                return

            try:
                new_server = ThreadingHTTPServer(("0.0.0.0", new_port), FileTransferHandler)
            except OSError as e:
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                err_resp = json.dumps(
                    {"success": False, "error": f"Port {new_port} is unavailable or in use: {e}"}
                ).encode("utf-8")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
                return

            new_thread = threading.Thread(target=new_server.serve_forever, daemon=True)
            new_thread.start()

            sender_sync.register_server(new_server)
            Config.LOCAL_PORT = new_port
            sender_sync.port = new_port

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            ok_resp = json.dumps(
                {
                    "success": True,
                    "port": new_port,
                    "redirect_url": f"http://127.0.0.1:{new_port}/sender",
                }
            ).encode("utf-8")
            self.send_header("Content-Length", str(len(ok_resp)))
            self.end_headers()
            self.wfile.write(ok_resp)

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            err_resp = json.dumps({"success": False, "error": str(e)}).encode("utf-8")
            self.send_header("Content-Length", str(len(err_resp)))
            self.end_headers()
            self.wfile.write(err_resp)

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

            # Query params for mode and port
            mode_name = "LAN"
            parsed_query = parse_qs(urlparse(self.path).query)
            if "mode" in parsed_query:
                mode_name = parsed_query["mode"][0]

            if "port" in parsed_query:
                try:
                    p = int(parsed_query["port"][0])
                    if 1 <= p <= 65535 and p != Config.LOCAL_PORT:
                        try:
                            new_server = ThreadingHTTPServer(("0.0.0.0", p), FileTransferHandler)
                            new_thread = threading.Thread(
                                target=new_server.serve_forever, daemon=True
                            )
                            new_thread.start()
                            sender_sync.register_server(new_server)
                            Config.LOCAL_PORT = p
                            sender_sync.port = p
                        except Exception as pe:
                            print(
                                f"{WRN} Could not rebind to port {p}, "
                                f"continuing on {Config.LOCAL_PORT}: {pe}"
                            )
                except (ValueError, TypeError):
                    pass

            from .tunnels import TunnelManager

            current_lan_ip = self.server_lan_ip or get_lan_ip()
            has_lan = bool(
                current_lan_ip
                and current_lan_ip not in ("None", "127.0.0.1", "localhost", "")
            )

            lan_notice = None
            if mode_name == "LAN" and not has_lan:
                print(
                    f"{INFO} Not in same LAN (no local network detected), "
                    "switching to the other connection..."
                )
                mode_name = "Cloudflare"
                lan_notice = "Not in same LAN, switching to the other connection..."

            lan_url = (
                f"http://{current_lan_ip}:{Config.LOCAL_PORT}"
                if has_lan
                else f"http://localhost:{Config.LOCAL_PORT}"
            )
            FileTransferHandler.lan_url = lan_url

            target_url = lan_url
            if mode_name != "LAN":
                tunnel_backend = (
                    mode_name.lower()
                    if mode_name in ("Cloudflare", "Ngrok", "SSH")
                    else None
                )
                noauth = mode_name != "Ngrok"
                if sender_sync.tunnel_manager:
                    try:
                        sender_sync.tunnel_manager.stop()
                    except Exception:
                        pass
                    sender_sync.tunnel_manager = None

                tm = TunnelManager(
                    Config.LOCAL_PORT,
                    noauth=noauth,
                    lan_only=False,
                    lan_ip=current_lan_ip,
                    tunnel_backend=tunnel_backend,
                )
                if not tm.start():
                    print(f"{WRN} Initial tunnel failed, trying fallback tunnel...")
                    tm = TunnelManager(
                        Config.LOCAL_PORT,
                        noauth=True,
                        lan_only=False,
                        lan_ip=current_lan_ip,
                        tunnel_backend="cloudflare" if tunnel_backend != "cloudflare" else None,
                    )
                    tm.start()

                if tm and (tm.public_url or tm.lan_url):
                    sender_sync.tunnel_manager = tm
                    if tm.public_url:
                        target_url = tm.public_url
                        FileTransferHandler.public_url = tm.public_url
                    else:
                        target_url = tm.lan_url
                        if not lan_notice:
                            lan_notice = f"Could not establish {mode_name} tunnel, running on LAN."
                        mode_name = "LAN"

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
            print(f"{OK} Files shared via Sender UI:")
            for fp in saved_paths:
                print(f"  - {os.path.basename(fp)} ({format_size(os.path.getsize(fp))})")
            print(f"  Mode : {mode_name}")
            print(f"  Port : {Config.LOCAL_PORT}")
            print(f"  Link : {target_url}")
            print(f"  Code : {Config.OTP}")
            print("=" * 60)

            resp_data = {
                "success": True,
                "is_send": True,
                "target_url": target_url,
                "pin": Config.OTP,
                "mode_name": mode_name,
                "port": Config.LOCAL_PORT,
                "notice": lan_notice,
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
a, a:hover, a:visited, a:focus, a:active { text-decoration:none !important; color:inherit; outline:none; }
button { font-family:inherit; outline:none; }
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
        submitButton.textContent = 'Not in same LAN, switching to the other connection...';
        if (window.ALT_CONNECTION_URL) {
            setTimeout(() => {
                window.location.href = window.ALT_CONNECTION_URL;
            }, 800);
        } else {
            alert('Not in same LAN so switching to the other connection...');
            submitButton.classList.add('enabled');
            submitButton.style.opacity = '1';
            submitButton.style.pointerEvents = 'auto';
            submitButton.textContent = 'Upload Files';
        }
    };

    xhr.open('POST', '/upload', true);
    xhr.send(formData);
});
window.ALT_CONNECTION_URL = "__ALT_URL__";
</script>
</body></html>"""
        alt_url = ""
        if FileTransferHandler.public_url and not self.is_tunnel_request():
            alt_url = FileTransferHandler.public_url
        elif FileTransferHandler.server_lan_ip and self.is_tunnel_request():
            alt_url = f"http://{FileTransferHandler.server_lan_ip}:{Config.LOCAL_PORT}"
        html = html.replace("__ALT_URL__", alt_url)
        html = html.replace("</body>", f"{self.get_receiver_session_script()}</body>")
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode())))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
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
a, a:hover, a:visited, a:focus, a:active { text-decoration:none !important; color:inherit; outline:none; }
button { font-family:inherit; outline:none; }
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

function triggerDownload(url, defaultFilename, isZip) {
    progressContainer.style.display = 'block';
    progressSpinner.style.display = 'inline-block';
    progressBar.style.width = '0%';
    progressPct.textContent = '0%';
    progressSpeed.textContent = '';
    progressStats.textContent = isZip ? 'Streaming ZIP archive...' : 'Starting download...';
    progressStatusText.textContent = isZip ? 'Streaming selected files as ZIP...' : 'Downloading ' + defaultFilename + '...';

    if (dlSelectedBtn) {
        dlSelectedBtn.style.opacity = '0.5';
        dlSelectedBtn.style.pointerEvents = 'none';
        selectedBtnText.textContent = isZip ? 'Streaming ZIP...' : 'Downloading...';
    }

    var a = document.createElement('a');
    a.href = url;
    a.download = defaultFilename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
        document.body.removeChild(a);
    }, 500);

    setTimeout(() => {
        if (dlSelectedBtn) {
            dlSelectedBtn.style.opacity = '1';
            dlSelectedBtn.style.pointerEvents = 'auto';
            updateSelection();
        }
    }, 2000);
}

try {
    var es = new EventSource('/api/receiver/events');
    es.addEventListener('progress', function(e) {
        try {
            var data = JSON.parse(e.data);
            if (data && data.total > 0) {
                progressContainer.style.display = 'block';
                progressSpinner.style.display = 'none';
                var pct = data.pct.toFixed(1);
                progressBar.style.width = pct + '%';
                progressPct.textContent = pct + '%';
                progressStats.textContent = formatBytes(data.transferred) + ' / ' + formatBytes(data.total);
                if (data.speed > 0) {
                    progressSpeed.textContent = formatBytes(data.speed) + '/s';
                }
                if (data.status === 'completed' || data.transferred >= data.total) {
                    progressStatusText.textContent = '✓ Download Complete!';
                    progressBar.style.width = '100%';
                    progressPct.textContent = '100%';
                    setTimeout(() => {
                        if (dlSelectedBtn) {
                            dlSelectedBtn.style.opacity = '1';
                            dlSelectedBtn.style.pointerEvents = 'auto';
                            updateSelection();
                        }
                    }, 1000);
                }
            }
        } catch(ex) {}
    });
} catch(ex) {}

if (dlSelectedBtn) {
    dlSelectedBtn.addEventListener('click', () => {
        var checkedIndices = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.getAttribute('data-idx'));
        if (!checkedIndices.length) return;
        var url = '/download/selected.zip?files=' + checkedIndices.join(',');
        triggerDownload(url, 'qrtunnel-selected.zip', true);
    });
}

document.querySelectorAll('.dl-single-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        e.preventDefault();
        var url = btn.getAttribute('href');
        var row = btn.closest('.file-item');
        var nameSpan = row ? row.querySelector('.file-name') : null;
        var displayName = nameSpan ? nameSpan.textContent.trim() : 'file';
        triggerDownload(url, displayName, false);
    });
});
window.ALT_CONNECTION_URL = "__ALT_URL__";
</script>
</body></html>"""
        alt_url = ""
        if FileTransferHandler.public_url and not self.is_tunnel_request():
            alt_url = FileTransferHandler.public_url
        elif FileTransferHandler.server_lan_ip and self.is_tunnel_request():
            alt_url = f"http://{FileTransferHandler.server_lan_ip}:{Config.LOCAL_PORT}"

        html = (
            template.replace("__FILE_LIST__", file_list_html)
            .replace("__FILE_COUNT__", str(len(self.file_paths)))
            .replace("__ALT_URL__", alt_url)
        )
        html = html.replace("</body>", f"{self.get_receiver_session_script()}</body>")
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode())))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
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

    def stream_zip_response(self, file_paths, zip_name, label=None):
        label = label or f"Download {zip_name}"
        try:
            entries = collect_zip_entries(file_paths)
            total_size = calculate_zip_size(entries)
            self.send_response(200)
            self.send_header("Content-type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{zip_name}"')
            self.send_header("Content-Length", str(total_size))
            self.send_header("Access-Control-Expose-Headers", "Content-Disposition, Content-Length")
            self._send_auth_cookie_if_needed()
            self.end_headers()
            self.wfile.flush()

            last_update = [0.0]

            def on_progress(sent, total):
                last_update[0] = self.print_progress(
                    label, sent, total, last_update=last_update[0]
                )

            stream_zip_archive(
                entries,
                self.wfile,
                chunk_size=1048576,
                progress_callback=on_progress,
            )
            self.wfile.flush()
            self.print_progress(label, total_size, total_size, force=True)
            print()
            print(f"{OK} ZIP archive '{zip_name}' served to {self.client_address[0]}")
            log_transfer(zip_name, total_size, self.client_address[0], "send")
        except BrokenPipeError:
            print(f"\n{ERR} Client disconnected during ZIP transfer of '{zip_name}'")
        except Exception as e:
            print(f"{ERR} Error serving ZIP archive '{zip_name}': {e}")
            if not self.wfile.closed:
                try:
                    self.send_error(500, "Internal Server Error")
                except Exception:
                    pass

    def serve_directory_zip(self, dir_path):
        dir_name = os.path.basename(dir_path.rstrip(os.sep))
        self.stream_zip_response(file_paths=[dir_path], zip_name=f"{dir_name}.zip")

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

            self.stream_zip_response(file_paths=selected_paths, zip_name="qrtunnel-selected.zip")
        except Exception as e:
            print(f"{ERR} Error serving selected ZIP archive: {e}")
            if not self.wfile.closed:
                try:
                    self.send_error(500, "Internal Server Error")
                except Exception:
                    pass

    def serve_zip_archive(self, file_paths=None, zip_name="qrtunnel-files.zip"):
        paths = file_paths if file_paths is not None else self.file_paths
        self.stream_zip_response(file_paths=paths, zip_name=zip_name)

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
            self.wfile.flush()
            is_range = bool(range_req)
            _transfer_tracker.start_stream(
                self.client_address[0], target_path, file_size, is_range
            )
            try:
                with open(target_path, "rb") as f:
                    if start > 0:
                        f.seek(start)
                    if platform.system() == "Linux" and hasattr(os, "sendfile"):
                        try:
                            sent = 0
                            last_update = 0
                            chunk_size = 1048576  # 1 MB slice for high wire throughput & smooth progress
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
                                agg_sent, _ = _transfer_tracker.update_sent(
                                    self.client_address[0], target_path, n
                                )
                                last_update = self.print_progress(
                                    f"Download {filename}",
                                    agg_sent,
                                    file_size,
                                    last_update=last_update,
                                )
                        except BrokenPipeError:
                            print(f"\n{ERR} Client disconnected during transfer of '{filename}'")
                    else:
                        try:
                            remaining = content_length
                            chunk_size = 1048576  # 1 MB
                            sent = 0
                            last_update = 0
                            while remaining > 0:
                                chunk = f.read(min(chunk_size, remaining))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                                sent += len(chunk)
                                agg_sent, _ = _transfer_tracker.update_sent(
                                    self.client_address[0], target_path, len(chunk)
                                )
                                last_update = self.print_progress(
                                    f"Download {filename}",
                                    agg_sent,
                                    file_size,
                                    last_update=last_update,
                                )
                            self.wfile.flush()
                        except BrokenPipeError:
                            print(f"\n{ERR} Client disconnected during transfer of '{filename}'")
            finally:
                is_last_stream = _transfer_tracker.finish_stream(
                    self.client_address[0], target_path
                )

            if is_last_stream:
                self.print_progress(
                    f"Download {filename}", file_size, file_size, force=True
                )
                print()
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
