"""Synchronization manager between Terminal and Sender Web UI."""

import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional


class SenderSync:
    """Thread-safe synchronization hub between TUI and Sender Web UI."""

    def __init__(self):
        self._lock = threading.Lock()
        self.port: int = 6969
        self.pin: str = ""
        self.lan_ip: str = ""
        self.mode_name: str = "LAN"
        self.is_send: bool = True
        self.is_active: bool = False
        self.file_paths: List[str] = []
        self.target_url: str = ""
        self.qr_svg: str = ""
        self.status: str = "idle"  # idle, waiting, transferring, completed, stopped
        self.received_files: List[Dict[str, Any]] = []

        # Progress tracking
        self.progress: Dict[str, Any] = {
            "status": "idle",
            "label": "",
            "transferred": 0,
            "total": 0,
            "pct": 0.0,
            "speed": 0.0,
        }
        self._last_progress_time: float = 0.0
        self._last_transferred: int = 0

        # Close and lifecycle synchronization
        self.closed_by_browser = threading.Event()
        self.closed_by_terminal = threading.Event()
        self.shutdown_event = threading.Event()
        self.transfer_started_event = threading.Event()

        # Heartbeat monitoring
        self.browser_connected = False
        self.last_heartbeat_time: float = 0.0
        self._watchdog_thread: Optional[threading.Thread] = None

        # SSE subscriber queues
        self._subscribers: List[queue.Queue] = []

        # Server instance reference
        self.server = None
        self.servers: List[Any] = []
        self.tunnel_manager = None

    def register_server(self, server: Any):
        with self._lock:
            self.server = server
            if server and server not in self.servers:
                self.servers.append(server)

    def shutdown_all_servers(self):
        with self._lock:
            to_stop = list(self.servers)
            if self.server and self.server not in to_stop:
                to_stop.append(self.server)
        for s in to_stop:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass

    def initialize(self, port: int, pin: str, lan_ip: Optional[str] = None):
        with self._lock:
            self.port = port
            self.pin = pin
            self.lan_ip = lan_ip or ""
            self.is_active = False
            self.status = "idle"
            self.received_files = []
            self.closed_by_browser.clear()
            self.closed_by_terminal.clear()
            self.shutdown_event.clear()
            self.transfer_started_event.clear()
            self.browser_connected = False
            self.last_heartbeat_time = 0.0
            if self.server and self.server not in self.servers:
                self.servers.append(self.server)
        self._start_watchdog()

    def set_active_transfer(
        self,
        is_send: bool,
        file_paths: List[str],
        mode_name: str,
        port: int,
        target_url: str,
        pin: str,
        qr_svg: str = "",
    ):
        with self._lock:
            self.is_active = True
            self.is_send = is_send
            self.file_paths = list(file_paths)
            self.mode_name = mode_name
            self.port = port
            self.target_url = target_url
            self.pin = pin
            self.qr_svg = qr_svg
            self.status = "waiting"
            self.transfer_started_event.set()

        self.broadcast_event("state", self.get_state())

    def update_progress(self, label: str, transferred: int, total: int):
        now = time.monotonic()
        with self._lock:
            elapsed = now - self._last_progress_time
            speed = 0.0
            if elapsed >= 0.2 and self._last_progress_time > 0:
                speed = max(0.0, (transferred - self._last_transferred) / elapsed)
                self._last_progress_time = now
                self._last_transferred = transferred
            elif self._last_progress_time == 0:
                self._last_progress_time = now
                self._last_transferred = transferred

            pct = round((transferred / total) * 100, 1) if total > 0 else 0.0
            status = "completed" if (total > 0 and transferred >= total) else "transferring"

            self.progress = {
                "status": status,
                "label": label,
                "transferred": transferred,
                "total": total,
                "pct": pct,
                "speed": speed,
            }
            prog_data = dict(self.progress)

        self.broadcast_event("progress", prog_data)

    def record_received_file(self, name: str, size: int):
        with self._lock:
            entry = {"name": name, "size": size, "time": time.time()}
            self.received_files.append(entry)
        self.broadcast_event("received", entry)

    def record_heartbeat(self):
        with self._lock:
            self.browser_connected = True
            self.last_heartbeat_time = time.monotonic()

    def close_from_browser(self):
        """Called when browser window is closed or sends close beacon."""
        if self.closed_by_browser.is_set() or self.shutdown_event.is_set():
            return
        self.closed_by_browser.set()
        self.shutdown_event.set()
        self.broadcast_event("close", {"source": "browser"})

    def close_from_terminal(self):
        """Called when terminal TUI or CLI exits."""
        if self.closed_by_terminal.is_set() or self.shutdown_event.is_set():
            return
        self.closed_by_terminal.set()
        self.shutdown_event.set()
        self.broadcast_event("close", {"source": "terminal"})

    def is_closed(self) -> bool:
        return self.closed_by_browser.is_set() or self.shutdown_event.is_set()

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            file_info = []
            for fp in self.file_paths:
                try:
                    sz = os.path.getsize(fp) if os.path.exists(fp) else 0
                except OSError:
                    sz = 0
                file_info.append({"name": os.path.basename(fp), "size": sz, "path": fp})

            return {
                "is_active": self.is_active,
                "is_send": self.is_send,
                "mode_name": self.mode_name,
                "port": self.port,
                "pin": self.pin,
                "lan_ip": self.lan_ip,
                "target_url": self.target_url,
                "qr_svg": self.qr_svg,
                "status": self.status,
                "files": file_info,
                "received_files": list(self.received_files),
                "progress": dict(self.progress),
            }

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def broadcast_event(self, event_type: str, data: Any):
        import json

        msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def _start_watchdog(self):
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return

        def watchdog():
            while not self.shutdown_event.is_set():
                time.sleep(1.0)
                with self._lock:
                    connected = self.browser_connected
                    last_hb = self.last_heartbeat_time

                # If browser was connected, but hasn't pinged in 5 seconds, close
                if connected and last_hb > 0:
                    if time.monotonic() - last_hb > 5.0:
                        self.close_from_browser()
                        break

        self._watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        self._watchdog_thread.start()


sender_sync = SenderSync()
