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
import sys
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
from .ui import (
    render_dashboard,
    render_download_page,
    render_login_page,
    render_receiver_session_script,
    render_upload_page,
    render_upload_success_page,
)
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

    def handle_error(self, request, client_address):
        """Suppress benign client disconnect tracebacks (BrokenPipe, ConnectionReset)."""
        exc_type, exc_val, _ = sys.exc_info()
        if exc_type in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        if isinstance(exc_val, (socket.error, OSError)) and getattr(exc_val, "errno", None) in (32, 104, 107):
            return
        super().handle_error(request, client_address)


class FileTransferHandler(BaseHTTPRequestHandler):
    def handle(self):
        """Handle multiple requests per connection gracefully, catching socket disconnects."""
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except OSError as e:
            if getattr(e, "errno", None) in (32, 104, 107):
                self.close_connection = True
            else:
                raise
        except Exception:
            self.close_connection = True

    def finish(self):
        """Safely release request socket resources without raising secondary broken pipe errors."""
        try:
            if not self.wfile.closed:
                try:
                    self.wfile.flush()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            super().finish()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except OSError as e:
            if getattr(e, "errno", None) in (32, 104, 107):
                pass
            else:
                raise
        except Exception:
            pass
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
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                print(f"{OK} Auth success from {self.client_address[0]}")
            else:
                print(f"{WRN} Failed auth attempt from {self.client_address[0]}")
                self.send_login_page(error="Incorrect 4-digit code")
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as e:
            print(f"{ERR} Auth error: {e}")
            if not self.wfile.closed:
                try:
                    self.send_error(500, "Internal Server Error")
                except Exception:
                    pass
            self.close_connection = True

    @staticmethod
    def get_receiver_session_script():
        return render_receiver_session_script()

    def send_login_page(self, error=None):
        html = render_login_page(error=error)
        encoded = html.encode("utf-8")
        self.send_response(200 if not error else 403)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        try:
            self.wfile.write(encoded)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

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
            if parsed_path.path == "/api/history":
                self.handle_history()
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
            if parsed_path.path == "/api/history/clear":
                self.handle_history_clear()
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
            self.send_header("Content-type", "text/html; charset=utf-8")
            success_html = self.get_upload_success_page(saved_files)
            encoded_success = success_html.encode("utf-8")
            self.send_header("Content-Length", str(len(encoded_success)))
            self.send_header("Connection", "close")
            self._send_auth_cookie_if_needed()
            self.end_headers()
            try:
                self.wfile.write(encoded_success)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            if target:
                target.cleanup()
            self.close_connection = True
            print(f"\n{ERR} Client disconnected during upload")
        except Exception as e:
            if target:
                target.cleanup()
            print(f"{ERR} Error during upload: {e}")
            if not self.wfile.closed:
                try:
                    self.send_error(500, "Internal Server Error")
                except Exception:
                    pass
            self.close_connection = True

    def get_upload_success_page(self, files):
        return render_upload_success_page(files)

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

        html = render_dashboard(
            current_lan_ip=current_lan_ip,
            has_lan=has_lan,
            pin_str=pin_str,
            port_val=port_val,
            rec_init_mode=rec_init_mode,
            rec_init_url=rec_init_url,
            rec_init_qr_svg=rec_init_qr_svg,
            cwd_name=cwd_name,
            initial_state_json=initial_state_json,
            default_tab=default_tab,
        )

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode("utf-8"))))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def handle_history(self):
        from .history import load_history
        entries = load_history()
        resp = json.dumps({"history": entries}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(resp)

    def handle_history_clear(self):
        from .history import clear_history
        clear_history()
        resp = json.dumps({"success": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(resp)

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
                        if getattr(tm, "fell_back_to_ssh", False) is True and mode_name == "Cloudflare":
                            mode_name = "SSH"
                            lan_notice = "Cloudflare unreachable (port 7844 blocked / Error 1033). Switched to SSH tunnel."
                        elif getattr(tm, "fell_back_to_cloudflare", False) is True and mode_name == "SSH":
                            mode_name = "Cloudflare"
                            lan_notice = "SSH tunnel unavailable. Switched to Cloudflare tunnel."
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
            self.close_connection = True
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
            self.close_connection = True
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
                        if getattr(tm, "fell_back_to_ssh", False) is True and mode_name == "Cloudflare":
                            mode_name = "SSH"
                            lan_notice = "Cloudflare unreachable (port 7844 blocked / Error 1033). Switched to SSH tunnel."
                        elif getattr(tm, "fell_back_to_cloudflare", False) is True and mode_name == "SSH":
                            mode_name = "Cloudflare"
                            lan_notice = "SSH tunnel unavailable. Switched to Cloudflare tunnel."
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
        html = render_upload_page()
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self._send_auth_cookie_if_needed()
        self.end_headers()
        try:
            self.wfile.write(encoded)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # ── download page ──
    def send_download_page(self):
        html = render_download_page(self.file_paths)
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self._send_auth_cookie_if_needed()
        self.end_headers()
        try:
            self.wfile.write(encoded)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

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
