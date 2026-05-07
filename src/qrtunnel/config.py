"""Runtime configuration values."""

from pathlib import Path


class Config:
    LOCAL_PORT = 8000
    OTP = None
    CONFIG_DIR = Path.home() / ".qrtunnel"
    CONFIG_FILE = CONFIG_DIR / "config.json"
