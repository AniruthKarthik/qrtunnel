"""Synchronization manager between Terminal and Sender Web UI."""

import atexit
import os
import queue
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config


def is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is currently alive across all platforms."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                exit_code = ctypes.c_ulong()
                # 259 is STILL_ACTIVE
                if kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                    kernel32.CloseHandle(h)
                    return exit_code.value == 259
                kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_subpath(child: Path, parent: Path) -> bool:
    """Check if child path is strictly inside parent path, cross-platform."""
    try:
        c = child.resolve()
        p = parent.resolve()
        if sys.platform == "win32":
            c_str = str(c).lower().replace("/", "\\")
            p_str = str(p).lower().replace("/", "\\")
            if not p_str.endswith("\\"):
                p_str += "\\"
            return c_str.startswith(p_str) and c_str != p_str.rstrip("\\")
        else:
            c.relative_to(p)
            return c != p
    except (ValueError, OSError):
        return False


def remove_dir_force(path: Path):
    """Safely and recursively remove a directory, handling read-only files on Windows."""

    def _handle_remove_readonly(func, p, excinfo):
        try:
            import stat

            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onerror=_handle_remove_readonly)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)


def cleanup_stale_staging_dirs(force: bool = False) -> int:
    """Clean up orphaned staging directories left behind by previous sessions or crashes.

    Args:
        force: If True (e.g. manual `qrtunnel clean`), remove all staging directories.
               If False (startup garbage collection), only remove directories owned by
               non-running processes or older than 15 minutes.

    Returns:
        int: Total number of bytes reclaimed.
    """
    staged_root = (Config.CONFIG_DIR / "staged").resolve()
    if not staged_root.exists() or not staged_root.is_dir():
        return 0

    reclaimed_bytes = 0
    current_pid = os.getpid()

    try:
        for entry in staged_root.iterdir():
            try:
                resolved_entry = entry.resolve()
                # Security guarantee: must be strictly inside Config.CONFIG_DIR / "staged"
                if not is_subpath(resolved_entry, staged_root):
                    continue

                should_delete = force

                if not should_delete and resolved_entry.is_dir():
                    pid_file = resolved_entry / ".owner_pid"
                    if pid_file.exists():
                        try:
                            owner_pid = int(pid_file.read_text().strip())
                            if owner_pid == current_pid or not is_pid_alive(owner_pid):
                                should_delete = True
                        except (ValueError, OSError):
                            should_delete = True
                    else:
                        try:
                            mtime = resolved_entry.stat().st_mtime
                            if time.time() - mtime > 900:  # 15 minutes
                                should_delete = True
                        except OSError:
                            should_delete = True

                if should_delete:
                    if resolved_entry.is_dir():
                        for root, _, files in os.walk(resolved_entry):
                            for f in files:
                                try:
                                    reclaimed_bytes += os.path.getsize(os.path.join(root, f))
                                except OSError:
                                    pass
                        remove_dir_force(resolved_entry)
                    elif resolved_entry.is_file():
                        try:
                            reclaimed_bytes += resolved_entry.stat().st_size
                            resolved_entry.unlink()
                        except OSError:
                            pass
            except (ValueError, OSError):
                continue
    except Exception:
        pass

    return reclaimed_bytes


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
        self.staged_dirs: List[Path] = []
        self.target_url: str = ""
        self.qr_svg: str = ""
        self.status: str = "idle"  # idle, waiting, transferring, completed, stopped
        self.received_files: List[Dict[str, Any]] = []

        # Register exit hook for automatic staging directory cleanup
        atexit.register(self.cleanup_staged_files)

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

    def register_staged_dir(self, staging_dir: Any):
        """Register a staging directory for automatic lifecycle cleanup."""
        path = Path(staging_dir)
        with self._lock:
            if path not in self.staged_dirs:
                self.staged_dirs.append(path)

    def cleanup_staged_files(self):
        """Clean up all staged files created during web UI transfers."""
        staged_root = (Config.CONFIG_DIR / "staged").resolve()

        with self._lock:
            dirs_to_clean = list(self.staged_dirs)
            self.staged_dirs.clear()

            # Remove staged file paths from active list while preserving original user files
            new_paths = []
            for fp in self.file_paths:
                if not is_subpath(Path(fp), staged_root):
                    new_paths.append(fp)
            self.file_paths = new_paths

        # Also safely clean FileTransferHandler.file_paths if it contains staged files
        try:
            from .server import FileTransferHandler

            if FileTransferHandler.file_paths:
                new_fth_paths = []
                for fp in FileTransferHandler.file_paths:
                    if not is_subpath(Path(fp), staged_root):
                        new_fth_paths.append(fp)
                FileTransferHandler.file_paths = new_fth_paths or None
        except Exception:
            pass

        for d in dirs_to_clean:
            try:
                p = Path(d).resolve()
                # Security: ONLY delete paths that are strictly subdirectories of CONFIG_DIR/staged
                if is_subpath(p, staged_root) and p.exists() and p.is_dir():
                    remove_dir_force(p)
            except Exception:
                pass

    def shutdown_all_servers(self):
        self.cleanup_staged_files()
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
        self.cleanup_staged_files()
        self.closed_by_browser.set()
        self.shutdown_event.set()
        self.broadcast_event("close", {"source": "browser"})

    def close_from_terminal(self):
        """Called when terminal TUI or CLI exits."""
        if self.closed_by_terminal.is_set() or self.shutdown_event.is_set():
            return
        self.cleanup_staged_files()
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
