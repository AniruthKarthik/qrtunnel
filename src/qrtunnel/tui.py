"""Interactive terminal UI."""

import os
import platform
import random
import sys

from .constants import (
    CLEAR,
    CLR_B,
    CLR_BLD,
    CLR_C,
    CLR_DIM,
    CLR_G,
    CLR_M,
    CLR_R,
    CLR_RST,
    CLR_W,
    CLR_Y,
    HIDE_CURSOR,
    SHOW_CURSOR,
    W,
    __version__,
)
from .keyboard import read_key
from .utils import format_size

# ─────────────────────────────────────────────────────────
#  TUI  –  the interactive arrow-key interface
# ─────────────────────────────────────────────────────────
# Screen IDs
SCR_MAIN = 0  # SEND / RECEIVE / EXIT
SCR_FILES = 1  # file-picker (SEND only)
SCR_MODE = 2  # tunnel-mode picker
SCR_PORT = 3  # port picker
SCR_CONFIRM = 4  # final review before launch


def _top_bar():
    """Return the shared top banner lines."""
    return [
        f"{CLR_DIM}{'─' * W}{CLR_RST}",
        f"  {CLR_B}{CLR_BLD}qrtunnel{CLR_RST}  {CLR_DIM}v{__version__}  •  cross-platform file transfer{CLR_RST}",
        f"{CLR_DIM}{'─' * W}{CLR_RST}",
    ]


def _nav_hint(back=True, fwd=True, search=False):
    """Small navigation hint line."""
    parts = []
    if back:
        parts.append(f"{CLR_DIM}← back{CLR_RST}")
    if fwd:
        parts.append(f"{CLR_DIM}→ proceed{CLR_RST}")
    parts.append(f"{CLR_DIM}↑↓ move{CLR_RST}")
    if search:
        parts.append(f"{CLR_C}/ search{CLR_RST}")
    parts.append(f"{CLR_R}q quit{CLR_RST}")
    return "  " + "   ".join(parts)


# ── Screen 0 – Main ──────────────────────────────────────
def draw_main(cursor):
    items = ["SEND", "RECEIVE", "EXIT"]
    icons = [CLR_G, CLR_B, CLR_R]
    lines = _top_bar()
    lines.append("")
    for i, (label, clr) in enumerate(zip(items, icons)):
        if i == cursor:
            lines.append(f"  {clr}{CLR_BLD}▸ {label}{CLR_RST}")
        else:
            lines.append(f"  {CLR_DIM}  {label}{CLR_RST}")
    lines.append("")
    lines.append(_nav_hint(back=False, fwd=True))
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines


# ── Screen 1 – File Picker ────────────────────────────────
def _list_dir(path):
    """Return sorted (dirs first, then files) entries of *path*."""
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return [], []
    dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
    files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
    return dirs, files


def draw_files(cursor, cwd, selected_files, scroll_offset, search_query="", is_searching=False):
    dirs, files = _list_dir(cwd)

    # Filter
    if search_query:
        q = search_query.lower()
        dirs = [d for d in dirs if q in d.lower()]
        files = [f for f in files if q in f.lower()]

    # build item list: [.. ] then dirs then files
    items = []  # (display_str,  full_path, kind)
    if cwd != os.path.abspath(os.sep) and not search_query:  # Hide '..' during search
        items.append(("  ..", None, "back"))
    for d in dirs:
        items.append((f"  {d}/", os.path.join(cwd, d), "dir"))
    for f in files:
        size = format_size(os.path.getsize(os.path.join(cwd, f)))
        items.append((f"  {f}", os.path.join(cwd, f), "file"))

    # viewport
    max_visible = 18
    if cursor >= len(items):
        cursor = len(items) - 1
    if cursor < 0:
        cursor = 0

    # Auto-scroll
    if cursor < scroll_offset:
        scroll_offset = cursor
    elif cursor >= scroll_offset + max_visible:
        scroll_offset = cursor - max_visible + 1

    visible_start = scroll_offset
    visible_end = min(len(items), scroll_offset + max_visible)

    lines = _top_bar()
    lines.append(f"  {CLR_M}{CLR_BLD}Select files to send{CLR_RST}")
    lines.append(f"  {CLR_DIM}{cwd}{CLR_RST}")

    # Search Bar
    if is_searching or search_query:
        prefix = "/" if is_searching else "Search:"
        cursor_char = "█" if is_searching else ""
        lines.append(f"  {CLR_Y}{prefix} {search_query}{cursor_char}{CLR_RST}")
    else:
        lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")

    if not items and search_query:
        lines.append(f"  {CLR_DIM}(No matches found){CLR_RST}")

    for idx in range(visible_start, visible_end):
        label, full, kind = items[idx]
        is_cursor = idx == cursor

        if kind == "back":
            txt = f"{CLR_Y}..{CLR_RST}"
            if is_cursor:
                lines.append(f"  {CLR_Y}{CLR_BLD}▸ {txt}{CLR_RST}")
            else:
                lines.append(f"    {txt}")
        elif kind == "dir":
            dname = os.path.basename(full)
            if is_cursor:
                lines.append(f"  {CLR_C}{CLR_BLD}▸ {dname}/{CLR_RST}")
            else:
                lines.append(f"  {CLR_C}  {dname}/{CLR_RST}")
        else:  # file
            fname = os.path.basename(full)
            size = format_size(os.path.getsize(full))
            is_sel = full in selected_files

            # Selection marker
            mark = f"{CLR_G}[x]{CLR_RST}" if is_sel else f"{CLR_DIM}[ ]{CLR_RST}"

            if is_cursor:
                lines.append(
                    f"  {CLR_W}{CLR_BLD}▸ {mark} {fname}{CLR_RST}  {CLR_DIM}{size}{CLR_RST}"
                )
            else:
                lines.append(f"    {mark} {fname}  {CLR_DIM}{size}{CLR_RST}")

    # scroll indicator
    if len(items) > max_visible:
        lines.append(f"  {CLR_DIM}({visible_start + 1}–{visible_end} / {len(items)}){CLR_RST}")

    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")

    # selected summary
    if selected_files:
        total = sum(os.path.getsize(f) for f in selected_files)
        lines.append(
            f"  {CLR_G}Selected: {len(selected_files)} file(s)  •  {format_size(total)}{CLR_RST}"
        )
    else:
        lines.append(f"  {CLR_DIM}No files selected{CLR_RST}")

    lines.append(_nav_hint(back=True, fwd=True, search=True))
    lines.append(f"  {CLR_DIM}Space/Enter = toggle   Enter on dir = open{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines, items


# ── Screen 2 – Mode ───────────────────────────────────────
MODE_OPTIONS = [
    ("Smart", "LAN + Public Tunnel  (auto high-speed)"),
    ("LAN", "Local network only   (fastest, same Wi-Fi)"),
    ("SSH", "localhost.run        (no sign-up)"),
    ("Ngrok", "ngrok tunnel         (requires account)"),
]


def draw_mode(cursor):
    lines = _top_bar()
    lines.append(f"  {CLR_C}{CLR_BLD}Select tunnel mode{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    for i, (name, desc) in enumerate(MODE_OPTIONS):
        if i == cursor:
            lines.append(f"  {CLR_M}{CLR_BLD}▸ {name:<8}{CLR_RST}  {desc}")
        else:
            lines.append(f"  {CLR_DIM}  {name:<8}  {desc}{CLR_RST}")
    lines.append("")
    lines.append(_nav_hint(back=True, fwd=True))
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines


# ── Screen 3 – Port ───────────────────────────────────────
PORT_OPTIONS = [
    ("Random", "Auto-pick a safe port (20 000–60 000)"),
    ("Custom", "Type your own port number"),
]


def draw_port(cursor, custom_port_str):
    lines = _top_bar()
    lines.append(f"  {CLR_Y}{CLR_BLD}Select port{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    for i, (name, desc) in enumerate(PORT_OPTIONS):
        if i == cursor:
            lines.append(f"  {CLR_Y}{CLR_BLD}▸ {name:<10}{CLR_RST}  {desc}")
        else:
            lines.append(f"  {CLR_DIM}  {name:<10}  {desc}{CLR_RST}")
    if cursor == 1:  # custom selected – show live input
        lines.append("")
        lines.append(f"  Port number:  {CLR_W}{CLR_BLD}{custom_port_str or '_'}{CLR_RST}")
    lines.append("")
    lines.append(_nav_hint(back=True, fwd=True))
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines


# ── Screen 4 – Confirm ────────────────────────────────────
def draw_confirm(mode_name, is_send, selected_files, port_val):
    lines = _top_bar()
    lines.append(f"  {CLR_G}{CLR_BLD}Ready to launch{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")

    action = "SEND" if is_send else "RECEIVE"
    lines.append(f"    Direction  →  {CLR_W}{action}{CLR_RST}")
    lines.append(f"    Tunnel     →  {CLR_W}{mode_name}{CLR_RST}")
    lines.append(f"    Port       →  {CLR_W}{port_val}{CLR_RST}")

    if is_send and selected_files:
        lines.append("")
        lines.append(f"    {CLR_DIM}Files:{CLR_RST}")
        total = 0
        for fp in selected_files:
            sz = os.path.getsize(fp)
            total += sz
            lines.append(f"      {CLR_DIM}{os.path.basename(fp)}  ({format_size(sz)}){CLR_RST}")
        lines.append(f"      {CLR_G}Total: {format_size(total)}{CLR_RST}")
    elif not is_send:
        lines.append(f"    {CLR_DIM}Receive dir  →  {os.getcwd()}{CLR_RST}")

    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    lines.append(f"  {CLR_G}{CLR_BLD}▸ LAUNCH{CLR_RST}    (Enter)")
    lines.append(f"  {CLR_DIM}  ← Back{CLR_RST}")
    lines.append(f"{CLR_DIM}{'─' * W}{CLR_RST}")
    return lines


# ── RENDER helper ─────────────────────────────────────────
def render(lines):
    """Clear screen and print all lines."""
    sys.stdout.write(CLEAR)
    # In raw mode on Unix, we need explicit carriage returns.
    sep = "\r\n" if platform.system() != "Windows" else "\n"
    sys.stdout.write(sep.join(lines))
    sys.stdout.write(sep)
    sys.stdout.flush()


class UnixRawMode:
    """Context manager to enable raw mode on Unix (no-op on Windows)."""

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.old_settings = None

    def __enter__(self):
        if platform.system() != "Windows":
            import termios
            import tty

            try:
                self.old_settings = termios.tcgetattr(self.fd)
                # tty.setraw disables all processing (input and output)
                tty.setraw(self.fd, termios.TCSADRAIN)
            except Exception:
                pass  # e.g. not a TTY
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.old_settings:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)


# ── MAIN TUI LOOP ─────────────────────────────────────────
def run_tui():
    """Drive the multi-screen TUI.  Returns (is_send, file_paths, mode, port) or None on exit."""
    # ── state ──
    screen = SCR_MAIN
    cursor = 0
    cwd = os.getcwd()
    selected_files = []
    mode_cursor = 0
    port_cursor = 0
    custom_port = ""  # live typed string
    custom_port_editing = False  # are we typing?
    file_scroll = 0

    # Search state
    search_query = ""
    is_searching = False

    # for RECEIVE we skip the file-picker so we remember where to resume
    screen_is_send = True
    # history stack: each push records (screen_id, cursor) so ← pops cleanly
    history = []

    def push(scr, cur):
        history.append((scr, cur))

    sys.stdout.write(HIDE_CURSOR)
    # Enable global raw mode for the duration of the TUI
    with UnixRawMode():
        try:
            while True:
                # ── DRAW ──
                if screen == SCR_MAIN:
                    render(draw_main(cursor))

                elif screen == SCR_FILES:
                    # Pass search state to draw_files
                    lines, items = draw_files(
                        cursor, cwd, selected_files, file_scroll, search_query, is_searching
                    )
                    render(lines)

                elif screen == SCR_MODE:
                    render(draw_mode(mode_cursor))

                elif screen == SCR_PORT:
                    render(draw_port(port_cursor, custom_port if port_cursor == 1 else None))

                elif screen == SCR_CONFIRM:
                    mode_name = MODE_OPTIONS[mode_cursor][0]
                    port_val = custom_port if (port_cursor == 1 and custom_port) else "Random"
                    render(draw_confirm(mode_name, screen_is_send, selected_files, port_val))

                # ── READ KEY ──
                key = read_key()
                if key is None:
                    continue
                if key == "CTRL_C":
                    return None

                # Global Quit (only if not typing text)
                if key == "q" and not custom_port_editing and not is_searching:
                    return None

                # ── HANDLE PER-SCREEN ──
                if screen == SCR_MAIN:
                    if key == "DOWN":
                        cursor = min(cursor + 1, 2)
                    elif key == "UP":
                        cursor = max(cursor - 1, 0)
                    elif key in ("ENTER", "RIGHT"):
                        if cursor == 0:  # SEND
                            screen_is_send = True
                            push(SCR_MAIN, 0)
                            screen = SCR_FILES
                            cursor = 0
                            file_scroll = 0
                            cwd = os.getcwd()
                        elif cursor == 1:  # RECEIVE
                            screen_is_send = False
                            push(SCR_MAIN, 1)
                            screen = SCR_MODE
                            mode_cursor = 0
                        else:  # EXIT
                            return None

                elif screen == SCR_FILES:
                    # Search Input Handling
                    if is_searching:
                        if key == "ESC":
                            is_searching = False
                            search_query = ""
                        elif key == "ENTER":
                            is_searching = False
                        elif key == "BACKSPACE":
                            search_query = search_query[:-1]
                        elif len(key) == 1 and key.isprintable():
                            search_query += key
                            # Reset cursor/scroll on typing
                            cursor = 0
                            file_scroll = 0
                        continue

                    # Normal Navigation
                    _, items = draw_files(
                        cursor, cwd, selected_files, file_scroll, search_query, is_searching
                    )
                    total_items = len(items)

                    if key == "/":  # Enter Search Mode
                        is_searching = True
                        continue

                    if key == "DOWN":
                        if cursor < total_items - 1:
                            cursor += 1
                            if cursor >= file_scroll + 18:
                                file_scroll += 1
                    elif key == "UP":
                        if cursor > 0:
                            cursor -= 1
                            if cursor < file_scroll:
                                file_scroll -= 1
                    elif key == "LEFT":  # ← back to main
                        if search_query:  # Clear search first if active
                            search_query = ""
                            cursor = 0
                            file_scroll = 0
                        else:
                            scr, cur = history.pop() if history else (SCR_MAIN, 0)
                            screen = scr
                            cursor = cur
                    elif key == "SPACE":  # toggle file
                        if cursor < total_items:
                            _, full, kind = items[cursor]
                            if kind == "file":
                                if full in selected_files:
                                    selected_files.remove(full)
                                else:
                                    selected_files.append(full)
                    elif key == "ENTER":
                        if cursor < total_items:
                            _, full, kind = items[cursor]
                            if kind == "back":
                                cwd = os.path.dirname(cwd)
                                cursor = 0
                                file_scroll = 0
                                search_query = ""  # reset search on dir change
                            elif kind == "dir":
                                cwd = full
                                cursor = 0
                                file_scroll = 0
                                search_query = ""  # reset search on dir change
                            else:  # file – toggle selection
                                if full in selected_files:
                                    selected_files.remove(full)
                                else:
                                    selected_files.append(full)
                    elif key == "RIGHT":  # → advance to MODE (only if files selected)
                        if selected_files:
                            push(SCR_FILES, cursor)
                            screen = SCR_MODE
                            mode_cursor = 0

                elif screen == SCR_MODE:
                    if key == "DOWN":
                        mode_cursor = min(mode_cursor + 1, len(MODE_OPTIONS) - 1)
                    elif key == "UP":
                        mode_cursor = max(mode_cursor - 1, 0)
                    elif key == "LEFT":
                        scr, cur = history.pop() if history else (SCR_MAIN, 0)
                        screen = scr
                        cursor = cur
                    elif key in ("ENTER", "RIGHT"):
                        push(SCR_MODE, mode_cursor)
                        screen = SCR_PORT
                        port_cursor = 0
                        custom_port = ""

                elif screen == SCR_PORT:
                    if custom_port_editing:
                        # capture typed digits
                        if key == "BACKSPACE":
                            custom_port = custom_port[:-1]
                        elif key in ("ENTER", "RIGHT"):
                            # validate
                            if custom_port.isdigit() and 1 <= int(custom_port) <= 65535:
                                custom_port_editing = False
                                push(SCR_PORT, port_cursor)
                                screen = SCR_CONFIRM
                            # else stay – let user fix
                        elif key == "LEFT":
                            custom_port_editing = False  # cancel typing, stay on screen
                        elif key and key.isdigit() and len(custom_port) < 5:
                            custom_port += key
                        continue  # skip the normal port-screen nav below

                    if key == "DOWN":
                        port_cursor = min(port_cursor + 1, 1)
                    elif key == "UP":
                        port_cursor = max(port_cursor - 1, 0)
                    elif key == "LEFT":
                        scr, cur = history.pop() if history else (SCR_MAIN, 0)
                        screen = scr
                        cursor = cur if scr != SCR_MODE else mode_cursor
                        mode_cursor = cur if scr == SCR_MODE else mode_cursor
                    elif key in ("ENTER", "RIGHT"):
                        if port_cursor == 0:  # random – go straight to confirm
                            custom_port = ""
                            push(SCR_PORT, port_cursor)
                            screen = SCR_CONFIRM
                        else:  # custom – start typing
                            custom_port = ""
                            custom_port_editing = True

                elif screen == SCR_CONFIRM:
                    if key in ("ENTER",):  # LAUNCH
                        break  # exit loop → caller launches
                    elif key in ("LEFT",):
                        scr, cur = history.pop() if history else (SCR_MAIN, 0)
                        screen = scr
                        # restore the right cursor variable
                        if scr == SCR_PORT:
                            port_cursor = cur
                        elif scr == SCR_MODE:
                            mode_cursor = cur
                        elif scr == SCR_FILES:
                            cursor = cur
                        else:
                            cursor = cur

        finally:
            sys.stdout.write(SHOW_CURSOR)
            sys.stdout.flush()

    # ── resolve final values ──
    mode_name = MODE_OPTIONS[mode_cursor][0]

    if port_cursor == 1 and custom_port.isdigit():
        final_port = int(custom_port)
    else:
        final_port = random.randint(20000, 60000)

    return screen_is_send, selected_files, mode_name, final_port


