"""Cross-platform helper to launch and close a dedicated browser window."""

import os
import platform
import shutil
import subprocess
import webbrowser
from typing import Optional

_browser_process: Optional[subprocess.Popen] = None


def launch_browser_window(url: str) -> Optional[subprocess.Popen]:
    """Open *url* in a new browser window (not tab) across Linux, macOS, and Windows."""
    global _browser_process

    # On Linux, verify display server is accessible
    if platform.system() == "Linux":
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return None

    # 1. Chromium-based browsers (support --app=URL for a dedicated window without tabs)
    chromium_candidates = [
        "brave",
        "brave-browser",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
    ]

    for name in chromium_candidates:
        binary = shutil.which(name)
        if binary:
            try:
                proc = subprocess.Popen(
                    [binary, f"--app={url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                _browser_process = proc
                return proc
            except Exception:
                try:
                    proc = subprocess.Popen(
                        [binary, "--new-window", url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    _browser_process = proc
                    return proc
                except Exception:
                    pass

    # 2. Firefox (--new-window)
    firefox_binary = shutil.which("firefox")
    if firefox_binary:
        try:
            proc = subprocess.Popen(
                [firefox_binary, "--new-window", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _browser_process = proc
            return proc
        except Exception:
            pass

    # 3. macOS native open command
    if platform.system() == "Darwin":
        for app in ("Google Chrome", "Brave Browser", "Microsoft Edge"):
            try:
                proc = subprocess.Popen(
                    ["open", "-na", app, "--args", f"--app={url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                _browser_process = proc
                return proc
            except Exception:
                pass
        try:
            proc = subprocess.Popen(
                ["open", "-n", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _browser_process = proc
            return proc
        except Exception:
            pass

    # 4. Windows start command
    if platform.system() == "Windows":
        for cmd in ("start chrome --app=", "start msedge --app=", "start brave --app="):
            try:
                proc = subprocess.Popen(
                    f'{cmd}"{url}"',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                _browser_process = proc
                return proc
            except Exception:
                pass

    # 5. Standard Python fallback
    try:
        webbrowser.open_new(url)
    except Exception:
        pass

    return None


def close_browser_window():
    """Terminate the browser process if active."""
    global _browser_process
    if _browser_process is not None:
        try:
            if _browser_process.poll() is None:
                _browser_process.terminate()
                _browser_process.wait(timeout=0.8)
        except Exception:
            try:
                _browser_process.kill()
            except Exception:
                pass
        finally:
            _browser_process = None
