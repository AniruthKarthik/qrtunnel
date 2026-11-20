import sys
import termios
from unittest.mock import patch

from qrtunnel import keyboard


def test_read_key_unix_non_tty(monkeypatch):
    """Verify _read_key_unix does not crash with UnboundLocalError when tcgetattr raises on non-TTY."""
    monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)
    with patch(
        "termios.tcgetattr", side_effect=termios.error(25, "Inappropriate ioctl for device")
    ):
        res = keyboard._read_key_unix()
        assert res is None


def test_read_key_unix_no_fileno(monkeypatch):
    """Verify _read_key_unix gracefully returns None when stdin has no fileno."""
    import io

    monkeypatch.setattr(
        sys.stdin, "fileno", lambda: (_ for _ in ()).throw(io.UnsupportedOperation())
    )
    assert keyboard._read_key_unix() is None


def test_read_key_win_kbhit_false_returns_none(monkeypatch):
    """Verify _read_key_win polls kbhit and returns None without blocking when no key is pressed."""
    from unittest.mock import MagicMock

    fake_msvcrt = MagicMock()
    fake_msvcrt.kbhit.return_value = False
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    with patch("time.sleep") as mock_sleep:
        res = keyboard._read_key_win()
        assert res is None
        assert fake_msvcrt.kbhit.called
        assert not fake_msvcrt.getch.called
        mock_sleep.assert_called_once_with(0.15)
