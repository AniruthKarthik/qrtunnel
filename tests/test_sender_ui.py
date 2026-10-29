"""Tests for Sender Web UI and synchronization."""

import io
import json
from unittest.mock import MagicMock, patch

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


def test_browser_launch_and_close():
    with patch("shutil.which", return_value="/usr/bin/mock-browser"):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            proc = launch_browser_window("http://127.0.0.1:6969/sender")
            assert proc is mock_proc
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert "--app=http://127.0.0.1:6969/sender" in args or "--new-window" in args

            close_browser_window()
            mock_proc.terminate.assert_called_once()
