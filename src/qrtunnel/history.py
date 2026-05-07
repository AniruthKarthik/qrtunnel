"""Local transfer history storage."""

import json
from datetime import datetime, timezone

from .config import Config
from .utils import format_size


def history_file():
    return Config.CONFIG_DIR / "history.json"


def load_history():
    path = history_file()
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def log_transfer(filename, size, client_ip, direction):
    Config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    entries = load_history()
    entries.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": direction,
            "filename": filename,
            "size": size,
            "client_ip": client_ip,
        }
    )
    with open(history_file(), "w") as f:
        json.dump(entries, f, indent=2)


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
