"""Tests for Sender Web UI and synchronization."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from qrtunnel.browser import close_browser_window, launch_browser_window
from qrtunnel.config import Config
from qrtunnel.qr import generate_qr_svg
from qrtunnel.server import FileTransferHandler
from qrtunnel.sync import SenderSync, sender_sync


def create_handler(path="/sender", method="GET", body=b""):
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.command = method
    handler.path = path
    handler.client_address = ("127.0.0.1", 54321)
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.headers = {}
    handler.close_connection = False
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    return handler


def test_generate_qr_svg():
    svg = generate_qr_svg("http://192.168.1.100:6969")
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "viewBox=" in svg
    assert "<rect" in svg


def test_sender_sync_state_and_progress():
    sync = SenderSync()
    sync.initialize(port=8080, pin="1234", lan_ip="192.168.1.50")
    assert sync.port == 8080
    assert sync.pin == "1234"
    assert sync.is_active is False
    assert not sync.is_closed()

    # Subscribe to events
    q = sync.subscribe()

    # Set active transfer
    sync.set_active_transfer(
        is_send=True,
        file_paths=["/tmp/test.txt"],
        mode_name="LAN",
        port=8080,
        target_url="http://192.168.1.50:8080",
        pin="1234",
        qr_svg="<svg></svg>",
    )
    assert sync.is_active is True
    assert sync.transfer_started_event.is_set()

    # Check event broadcast
    evt = q.get_nowait()
    assert "event: state" in evt
    assert '"is_active": true' in evt

    # Update progress
    sync.update_progress("Test", 50, 100)
    evt2 = q.get_nowait()
    assert "event: progress" in evt2
    data = json.loads(evt2.split("data: ")[1].strip())
    assert data["pct"] == 50.0
    assert data["transferred"] == 50
    assert data["total"] == 100
    assert data["status"] == "transferring"

    # Complete progress
    sync.update_progress("Test", 100, 100)
    evt3 = q.get_nowait()
    data2 = json.loads(evt3.split("data: ")[1].strip())
    assert data2["pct"] == 100.0
    assert data2["status"] == "completed"

    sync.unsubscribe(q)


def test_sender_sync_close_events():
    sync = SenderSync()
    sync.initialize(port=6969, pin="0000")
    q = sync.subscribe()

    assert not sync.is_closed()
    sync.close_from_browser()
    assert sync.is_closed()
    assert sync.closed_by_browser.is_set()
    assert sync.shutdown_event.is_set()

    close_evt = q.get_nowait()
    assert "event: close" in close_evt
    assert '"source": "browser"' in close_evt

    # Terminal close
    sync2 = SenderSync()
    sync2.initialize(port=6969, pin="0000")
    q2 = sync2.subscribe()
    sync2.close_from_terminal()
    assert sync2.is_closed()
    assert sync2.closed_by_terminal.is_set()

    close_evt2 = q2.get_nowait()
    assert "event: close" in close_evt2
    assert '"source": "terminal"' in close_evt2


def test_sender_page_get(tmp_path):
    sender_sync.initialize(port=6969, pin="4321", lan_ip="10.0.0.5")

    handler = create_handler(path="/sender", method="GET")
    handler.send_sender_page()

    handler.send_response.assert_called_with(200)
    output = handler.wfile.getvalue().decode("utf-8")
    assert "qrtunnel - Sender" in output
    assert "file-drop-area" in output
    assert "drop-area" in output
    assert "file-preview-area" in output
    assert "progress-container" in output
    assert "progress-bar" in output
    assert "stop-btn" in output


def test_sender_api_state(tmp_path):
    sender_sync.initialize(port=6969, pin="9999", lan_ip="10.0.0.5")
    test_file = tmp_path / "hello.txt"
    test_file.write_text("Hello World!")
    sender_sync.set_active_transfer(
        is_send=True,
        file_paths=[str(test_file)],
        mode_name="LAN",
        port=6969,
        target_url="http://10.0.0.5:6969",
        pin="9999",
        qr_svg="<svg>QR</svg>",
    )

    handler = create_handler(path="/api/sender/state", method="GET")
    handler.handle_sender_state()

    handler.send_response.assert_called_with(200)
    body = handler.wfile.getvalue().decode("utf-8")
    data = json.loads(body)
    assert data["is_active"] is True
    assert data["pin"] == "9999"
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "hello.txt"
    assert data["files"][0]["size"] == 12


def test_sender_api_close_and_heartbeat():
    sender_sync.initialize(port=6969, pin="1111")
    handler = create_handler(path="/api/sender/heartbeat", method="POST")

    handler.handle_sender_heartbeat()
    assert sender_sync.browser_connected is True
    assert sender_sync.last_heartbeat_time > 0
    handler.send_response.assert_called_with(204)

    assert not sender_sync.is_closed()
    handler2 = create_handler(path="/api/sender/close", method="POST")
    handler2.handle_sender_close()
    assert sender_sync.is_closed()
    assert sender_sync.closed_by_browser.is_set()
    handler2.send_response.assert_called_with(204)


def test_sender_api_share_multiple_files(tmp_path):
    sender_sync.initialize(port=6969, pin="2222", lan_ip="127.0.0.1")
    Config.LOCAL_PORT = 6969
    Config.OTP = "2222"
    FileTransferHandler.server_lan_ip = "127.0.0.1"

    # Construct multipart form body with 2 files
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    part1 = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="file1.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "File 1 Content\r\n"
    )
    part2 = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="file2.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
        "Binary Content 2\r\n"
    )
    part_end = f"--{boundary}--\r\n"
    body_bytes = part1.encode("utf-8") + part2.encode("utf-8") + part_end.encode("utf-8")

    handler = create_handler(path="/api/sender/share?mode=LAN", method="POST", body=body_bytes)
    handler.headers = {
        "Content-Length": str(len(body_bytes)),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    with patch("qrtunnel.qr.generate_qr_code"):
        handler.handle_sender_share()

    handler.send_response.assert_called_with(200)
    resp_body = handler.wfile.getvalue().decode("utf-8")
    res = json.loads(resp_body)
    assert res["success"] is True
    assert len(res["files"]) == 2
    assert res["files"][0]["name"] == "file1.txt"
    assert res["files"][1]["name"] == "file2.bin"
    assert sender_sync.is_active is True
    assert len(sender_sync.file_paths) == 2


def test_browser_launch_and_safe_close(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    with patch("shutil.which", return_value="/usr/bin/mock-browser"):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            proc = launch_browser_window("http://127.0.0.1:6969/sender")
            assert proc is mock_proc
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert (
                "http://127.0.0.1:6969/sender" in args
                or "--app=http://127.0.0.1:6969/sender" in args
                or "--new-window" in args
            )

            # close_browser_window is a safe no-op to prevent closing other tabs
            close_browser_window()
            mock_proc.terminate.assert_not_called()


def test_browser_launch_headless_linux(monkeypatch):
    """Verify launch_browser_window returns None on headless Linux (no DISPLAY or WAYLAND)."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with patch("platform.system", return_value="Linux"):
        proc = launch_browser_window("http://127.0.0.1:6969/sender")
        assert proc is None


def test_parse_args_direct_and_tui(monkeypatch):
    from qrtunnel.app import parse_args

    # Direct qrtunnel run (UI Mode, command is None)
    monkeypatch.setattr("sys.argv", ["qrtunnel"])
    args, port = parse_args()
    assert args.command is None
    assert port == 6969

    # Direct with custom port -8080
    monkeypatch.setattr("sys.argv", ["qrtunnel", "-8080"])
    args, port = parse_args()
    assert args.command is None
    assert port == 8080

    # Explicit qrtunnel tui command
    monkeypatch.setattr("sys.argv", ["qrtunnel", "tui"])
    args, port = parse_args()
    assert args.command == "tui"
    assert port == 6969

    # Explicit qrtunnel tui with port
    monkeypatch.setattr("sys.argv", ["qrtunnel", "tui", "-9090"])
    args, port = parse_args()
    assert args.command == "tui"
    assert port == 9090

    # Explicit qrtunnel ui command is NOT allowed (only 'qrtunnel tui' triggers TUI)
    monkeypatch.setattr("sys.argv", ["qrtunnel", "ui"])
    with pytest.raises(SystemExit):
        parse_args()


def test_sender_page_has_port_input_and_lan_notice():
    handler = create_handler("/sender", method="GET")
    handler.send_sender_page()
    html = handler.wfile.getvalue().decode("utf-8")
    assert 'id="port-input"' in html
    assert 'id="apply-port-btn"' in html
    assert 'id="lan-switch-notice"' in html
    assert 'id="lan-mode-notice"' in html
    assert "Not in same LAN, switching to the other connection..." in html
    # Ensure port application does NOT reload the page and clear files
    assert "window.location.href = data.redirect_url" not in html


def test_sender_sync_multi_servers():
    sync = SenderSync()
    s1 = MagicMock()
    s2 = MagicMock()
    sync.register_server(s1)
    sync.register_server(s2)
    assert sync.server == s2
    assert s1 in sync.servers
    assert s2 in sync.servers

    sync.shutdown_all_servers()
    s1.shutdown.assert_called_once()
    s1.server_close.assert_called_once()
    s2.shutdown.assert_called_once()
    s2.server_close.assert_called_once()


def test_handle_sender_port():
    handler = create_handler("/api/sender/port", method="POST", body=b'{"port": 9876}')
    handler.headers = {"Content-Length": "16", "Content-Type": "application/json"}
    with patch("qrtunnel.server.ThreadingHTTPServer") as mock_server_cls:
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        handler.handle_sender_port()

        handler.send_response.assert_called_with(200)
        resp_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        assert resp_data["success"] is True
        assert resp_data["port"] == 9876
        assert resp_data["redirect_url"] == "http://127.0.0.1:9876/sender"
        assert Config.LOCAL_PORT == 9876
        assert sender_sync.port == 9876

    # Test invalid port (out of range)
    Config.LOCAL_PORT = 6969
    sender_sync.port = 6969
    handler_bad = create_handler("/api/sender/port", method="POST", body=b'{"port": 99999}')
    handler_bad.headers = {"Content-Length": "17", "Content-Type": "application/json"}
    handler_bad.handle_sender_port()
    handler_bad.send_response.assert_called_with(400)


def test_handle_sender_share_lan_fallback(tmp_path):
    f1 = tmp_path / "doc.txt"
    f1.write_text("sample content")

    boundary = "----WebKitFormBoundaryLanFallback"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="doc.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "sample content\r\n"
        f"--{boundary}--\r\n"
    )
    body_bytes = body.encode("utf-8")

    handler = create_handler(path="/api/sender/share?mode=LAN", method="POST", body=body_bytes)
    handler.headers = {
        "Content-Length": str(len(body_bytes)),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    # Simulate host not having a LAN IP
    with patch("qrtunnel.server.get_lan_ip", return_value=None):
        with patch("qrtunnel.tunnels.TunnelManager") as mock_tm_cls:
            mock_tm = MagicMock()
            mock_tm.start.return_value = True
            mock_tm.public_url = "https://fallback.trycloudflare.com"
            mock_tm.lan_url = "http://localhost:6969"
            mock_tm_cls.return_value = mock_tm

            handler.handle_sender_share()

    handler.send_response.assert_called_with(200)
    resp = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert resp["success"] is True
    assert resp["notice"] == "Not in same LAN, switching to the other connection..."
    assert resp["mode_name"] == "Cloudflare"
    assert resp["target_url"] == "https://fallback.trycloudflare.com"


def test_receiver_pages_contain_session_closed_handling(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("content")

    handler = create_handler(path="/", method="GET")
    handler.file_paths = [str(f)]

    # 1. Download page
    handler.send_download_page()
    dl_html = handler.wfile.getvalue().decode("utf-8")
    assert "Session Closed" in dl_html
    assert "You can safely close this window." in dl_html
    assert "/api/session/status" in dl_html
    assert "/api/receiver/events" in dl_html

    # 2. Upload page
    handler2 = create_handler(path="/", method="GET")
    handler2.file_paths = []
    handler2.upload_mode = True
    handler2.send_upload_page()
    up_html = handler2.wfile.getvalue().decode("utf-8")
    assert "Session Closed" in up_html
    assert "You can safely close this window." in up_html

    # 3. Upload success page
    success_html = handler2.get_upload_success_page("sample.png")
    assert "Session Closed" in success_html
    assert "You can safely close this window." in success_html

    # 4. Login page
    handler3 = create_handler(path="/", method="GET")
    handler3.send_login_page()
    login_html = handler3.wfile.getvalue().decode("utf-8")
    assert "Session Closed" in login_html
    assert "You can safely close this window." in login_html


def test_session_status_and_receiver_events():
    sender_sync.initialize(port=6969, pin="1234")

    # Status when active
    h_status = create_handler(path="/api/session/status", method="GET")
    h_status.handle_session_status()
    h_status.send_response.assert_called_with(200)
    data = json.loads(h_status.wfile.getvalue().decode("utf-8"))
    assert data["closed"] is False

    # Close session
    sender_sync.close_from_terminal()

    # Status when closed
    h_status_closed = create_handler(path="/api/session/status", method="GET")
    h_status_closed.handle_session_status()
    data_closed = json.loads(h_status_closed.wfile.getvalue().decode("utf-8"))
    assert data_closed["closed"] is True

    # Receiver events SSE when closed
    h_events = create_handler(path="/api/receiver/events", method="GET")
    h_events.handle_receiver_events()
    events_output = h_events.wfile.getvalue().decode("utf-8")
    assert "event: close" in events_output
    assert '"closed": true' in events_output


def test_check_auth_exempts_receiver_session_endpoints():
    handler = create_handler(path="/api/session/status", method="GET")
    handler.client_address = ("192.168.1.105", 54321)
    handler.authorized_sessions = set()
    assert handler.check_auth() is True

    handler2 = create_handler(path="/api/receiver/events", method="GET")
    handler2.client_address = ("192.168.1.105", 54321)
    handler2.authorized_sessions = set()
    assert handler2.check_auth() is True
