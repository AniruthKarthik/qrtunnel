"""Cross-platform single-key input helpers."""

import platform
import sys


# ─────────────────────────────────────────────────────────
#  LOW-LEVEL KEYBOARD READING  (cross-platform)
# ─────────────────────────────────────────────────────────
def _read_key_unix():
    """Blocking single-key read on Unix; returns a string token."""
    import os
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()

    # Check if canonical mode is enabled (cooked) or disabled (raw)
    # lflags is the 4th element (index 3)
    try:
        attrs = termios.tcgetattr(fd)
        is_canonical = attrs[3] & termios.ICANON
    except Exception:
        is_canonical = True  # Assume cooked if we can't tell

    try:
        if is_canonical:
            # Switch to cbreak mode temporarily (raw input, but processed output)
            # This prevents "staircase" printing when other threads print to stdout
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd, termios.TCSADRAIN)

        # Select on the FILE DESCRIPTOR, not the sys.stdin object
        if not select.select([fd], [], [], 0.15)[0]:
            return None

        # Read raw bytes from FD to avoid Python buffering issues
        try:
            b = os.read(fd, 1)
        except OSError:
            return None

        if not b:
            return None

        # Simple decode
        try:
            ch = b.decode()
        except UnicodeDecodeError:
            return None

        if ch == "\x1b":
            # possible escape sequence – read more if available
            # 0.1s timeout should be plenty for local or ssh
            if select.select([fd], [], [], 0.1)[0]:
                b2 = os.read(fd, 1)
                ch2 = b2.decode(errors="ignore")

                # Handle '[' (CSI) and 'O' (SS3)
                if ch2 == "[" or ch2 == "O":
                    if select.select([fd], [], [], 0.1)[0]:
                        b3 = os.read(fd, 1)
                        ch3 = b3.decode(errors="ignore")

                        if ch3 == "A":
                            return "UP"
                        if ch3 == "B":
                            return "DOWN"
                        if ch3 == "C":
                            return "RIGHT"
                        if ch3 == "D":
                            return "LEFT"
                        if ch2 == "[" and ch3 == "~":
                            return "FUNC"
                        return None
                    return None
                return None
            return "ESC"
        if ch == "\r" or ch == "\n":
            return "ENTER"
        if ch == " ":
            return "SPACE"
        if ch == "\x7f" or ch == "\x08":
            return "BACKSPACE"
        if ch == "\x03":
            return "CTRL_C"
        if ch.isprintable():
            return ch
        return None

    finally:
        if is_canonical:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key_win():
    """Blocking single-key read on Windows."""
    import msvcrt

    ch = msvcrt.getch()
    if ch in (b"\xe0", b"\x00"):
        ch2 = msvcrt.getch()
        codes = {72: "UP", 80: "DOWN", 77: "RIGHT", 75: "LEFT"}
        return codes.get(ch2[0] if isinstance(ch2, bytes) else ch2)
    if ch in (b"\r", b"\n"):
        return "ENTER"
    if ch == b" ":
        return "SPACE"
    if ch in (b"\x7f", b"\x08"):
        return "BACKSPACE"
    if ch == b"\x03":
        return "CTRL_C"
    try:
        c = ch.decode()
        if c.isprintable():
            return c
    except Exception:
        pass
    return None


def read_key():
    """Cross-platform blocking key reader.  Returns a string token or None."""
    if platform.system() == "Windows":
        return _read_key_win()
    return _read_key_unix()


