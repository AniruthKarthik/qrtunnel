"""qrtunnel public API."""

from .config import Config
from .constants import __version__
from .hotspot import HotspotHelper
from .keyboard import read_key
from .qr import generate_qr_code
from .utils import format_size, get_lan_ip, is_same_lan

__all__ = [
    "Config",
    "FileTransferHandler",
    "HotspotHelper",
    "NgrokAuth",
    "NgrokTunnel",
    "SSHTunnel",
    "ThreadingHTTPServer",
    "TunnelManager",
    "__version__",
    "format_size",
    "generate_qr_code",
    "get_lan_ip",
    "get_windows_ngrok_install_hint",
    "is_same_lan",
    "load_history",
    "log_transfer",
    "launch_server",
    "main",
    "parse_args",
    "read_key",
    "run_tui",
]


def __getattr__(name):
    if name in {"launch_server", "main", "parse_args"}:
        from . import app

        return getattr(app, name)
    if name in {"FileTransferHandler", "ThreadingHTTPServer"}:
        from . import server

        return getattr(server, name)
    if name == "run_tui":
        from . import tui

        return getattr(tui, name)
    if name in {"CloudflareTunnel", "NgrokAuth", "NgrokTunnel", "SSHTunnel", "TunnelManager"}:
        from . import tunnels

        return getattr(tunnels, name)
    if name == "get_windows_ngrok_install_hint":
        from . import tunnels

        return tunnels.get_windows_ngrok_install_hint
    if name in {"load_history", "log_transfer", "print_history"}:
        from . import history

        return getattr(history, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
