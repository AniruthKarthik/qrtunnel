"""Local transfer history storage."""

import json
import os
import threading
from datetime import datetime, timezone

from .config import Config
from .utils import format_size

_history_lock = threading.Lock()


def history_file():
    return Config.CONFIG_DIR / "history.json"


def _atomic_write_json(path, data):
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    temp_path = dir_path / f".{path.name}.tmp.{threading.get_ident()}"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def load_history():
    path = history_file()
    if not path.exists():
        return []
    with _history_lock:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        return data if isinstance(data, list) else []


def clear_history():
    with _history_lock:
        _atomic_write_json(history_file(), [])


def log_transfer(filename, size, client_ip, direction):
    with _history_lock:
        path = history_file()
        entries = []
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        entries = data
            except Exception:
                entries = []

        entries.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "direction": direction,
                "filename": filename,
                "size": size,
                "client_ip": client_ip,
            }
        )
        _atomic_write_json(path, entries)


def print_history(limit=20):
    entries = load_history()[-limit:]
    if not entries:
        print("No transfer history found.")
        return

    for entry in entries:
        print(
            f"{entry.get('timestamp', '-')}  "
            f"{entry.get('direction', '-'):7}  "
            f"{format_size(entry.get('size', 0)):>10}  "
            f"{entry.get('client_ip', '-'):15}  "
            f"{entry.get('filename', '-')}"
        )
