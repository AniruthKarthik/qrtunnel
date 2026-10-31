"""Tests for Receive Web Page (/receive) and tunnel mode selection."""

import io
import json
from unittest.mock import MagicMock, patch

from qrtunnel import tunnels
from qrtunnel.server import FileTransferHandler
from qrtunnel.sync import sender_sync


def create_handler(path="/receive", method="GET", body=b"", client_ip="127.0.0.1"):
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.command = method
    handler.path = path
    handler.client_address = (client_ip, 54321)
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.headers = {}
    handler.close_connection = False
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    return handler


class FakeTunnel:
    def __init__(self, local_port, name, url="https://example.com", succeeds=True):
        self.local_port = local_port
        self.name = name
        self.public_url = url
        self.succeeds = succeeds

    def start(self):
        return self.succeeds

    def stop(self):
        pass


def test_receive_page_html_structure():
    sender_sync.initialize(port=6969, pin="1234", lan_ip="192.168.1.10")
    handler = create_handler(path="/receive", method="GET")

    handler.send_receive_page()

    html = handler.wfile.getvalue().decode("utf-8")
    handler.send_response.assert_called_with(200)

    # Header and title
    assert "Receive Files" in html
    assert "Select connection mode to show QR code for upload" in html

    # Connection Mode buttons
    assert 'data-mode="LAN"' in html
    assert 'data-mode="Cloudflare"' in html
    assert 'data-mode="SSH"' in html
    assert 'data-mode="Ngrok"' in html

    # Port section
    assert 'id="port-input"' in html
    assert 'id="port-apply-btn"' in html

    # QR and URL section
    assert 'id="qr-wrapper"' in html
    assert 'id="pin-display"' in html
    assert 'id="target-url-text"' in html
    assert 'id="copy-btn"' in html

    # Incoming transfers section
    assert "Incoming Transfers" in html
    assert 'id="received-list"' in html
    assert 'id="empty-state"' in html

    # Controls
    assert 'id="close-session-btn"' in html
    assert 'href="/sender"' in html


def test_do_get_routes_local_to_receive():
    FileTransferHandler.upload_mode = True
    FileTransferHandler.file_paths = None

    # Local client accessing / or /receive gets send_receive_page
    h_receive = create_handler(path="/receive", method="GET", client_ip="127.0.0.1")
    with patch.object(h_receive, "send_receive_page") as mock_page:
        h_receive.do_GET()
        mock_page.assert_called_once()

    h_root = create_handler(path="/", method="GET", client_ip="127.0.0.1")
    with patch.object(h_root, "send_receive_page") as mock_root_page:
        h_root.do_GET()
        mock_root_page.assert_called_once()


def test_do_get_routes_remote_to_upload():
    FileTransferHandler.upload_mode = True
    FileTransferHandler.file_paths = None

    # Remote client accessing / gets upload page (not receive dashboard)
    h_remote = create_handler(path="/", method="GET", client_ip="192.168.1.55")
    with patch.object(h_remote, "check_auth", return_value=True):
        with patch.object(h_remote, "send_upload_page") as mock_up:
            h_remote.do_GET()
            mock_up.assert_called_once()


def test_handle_receiver_mode_switch_to_cloudflare():
    sender_sync.initialize(port=6969, pin="1234", lan_ip="192.168.1.10")

    handler = create_handler(path="/api/receiver/mode?mode=Cloudflare&port=6969", method="POST")
    fake_cf = FakeTunnel(
        6969, "cloudflared", url="https://mock-cf.trycloudflare.com", succeeds=True
    )

    with patch("qrtunnel.tunnels.CloudflareTunnel", return_value=fake_cf):
        handler.handle_receiver_mode()

    handler.send_response.assert_called_with(200)
    resp = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert resp["success"] is True
    assert resp["mode_name"] == "Cloudflare"
    assert resp["target_url"] == "https://mock-cf.trycloudflare.com"
    assert resp["is_send"] is False
    assert "<svg" in resp["qr_svg"]


def test_handle_receiver_mode_switch_to_ssh():
    sender_sync.initialize(port=6969, pin="1234", lan_ip="192.168.1.10")

    handler = create_handler(path="/api/receiver/mode?mode=SSH&port=6969", method="POST")
    fake_ssh = FakeTunnel(6969, "localhost.run", url="https://mock-ssh.lhr.life", succeeds=True)

    with patch("qrtunnel.tunnels.SSHTunnel", return_value=fake_ssh):
        handler.handle_receiver_mode()

    handler.send_response.assert_called_with(200)
    resp = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert resp["success"] is True
    assert resp["mode_name"] == "SSH"
    assert resp["target_url"] == "https://mock-ssh.lhr.life"
    assert resp["is_send"] is False


def test_handle_receiver_mode_switch_to_lan():
    sender_sync.initialize(port=6969, pin="1234", lan_ip="192.168.1.10")

    handler = create_handler(path="/api/receiver/mode?mode=LAN&port=6969", method="POST")
    handler.server_lan_ip = "192.168.1.10"

    handler.handle_receiver_mode()

    handler.send_response.assert_called_with(200)
    resp = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert resp["success"] is True
    assert resp["mode_name"] == "LAN"
    assert "192.168.1.10:6969" in resp["target_url"]


def test_handle_receiver_mode_lan_fallback_when_no_lan():
    sender_sync.initialize(port=6969, pin="1234", lan_ip=None)

    handler = create_handler(path="/api/receiver/mode?mode=LAN&port=6969", method="POST")
    handler.server_lan_ip = None

    fake_cf = FakeTunnel(
        6969, "cloudflared", url="https://auto-fallback.trycloudflare.com", succeeds=True
    )

    with patch("qrtunnel.server.get_lan_ip", return_value=None):
        with patch("qrtunnel.tunnels.CloudflareTunnel", return_value=fake_cf):
            handler.handle_receiver_mode()

    handler.send_response.assert_called_with(200)
    resp = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert resp["success"] is True
    assert resp["notice"] == "Not in same LAN, switching to Cloudflare tunnel..."
    assert resp["mode_name"] == "Cloudflare"
    assert resp["target_url"] == "https://auto-fallback.trycloudflare.com"


def test_receiver_records_file_and_broadcasts():
    sender_sync.initialize(port=6969, pin="1234")
    q = sender_sync.subscribe()

    assert len(sender_sync.received_files) == 0

    sender_sync.record_received_file("photo.jpg", 102400)

    assert len(sender_sync.received_files) == 1
    assert sender_sync.received_files[0]["name"] == "photo.jpg"
    assert sender_sync.received_files[0]["size"] == 102400

    evt = q.get_nowait()
    assert "event: received" in evt
    data = json.loads(evt.split("data: ")[1].strip())
    assert data["name"] == "photo.jpg"
    assert data["size"] == 102400

    sender_sync.unsubscribe(q)


def test_tunnel_manager_explicit_backends():
    # 1. SSH backend explicitly invokes SSHTunnel
    fake_ssh = FakeTunnel(8080, "ssh", url="https://ssh-direct.lhr.life", succeeds=True)
    with patch("qrtunnel.tunnels.SSHTunnel", return_value=fake_ssh):
        tm_ssh = tunnels.TunnelManager(8080, tunnel_backend="ssh")
        assert tm_ssh.start() is True
        assert tm_ssh.public_url == "https://ssh-direct.lhr.life"

    # 2. Cloudflare backend explicitly invokes CloudflareTunnel
    fake_cf = FakeTunnel(8080, "cf", url="https://cf-direct.trycloudflare.com", succeeds=True)
    with patch("qrtunnel.tunnels.CloudflareTunnel", return_value=fake_cf):
        tm_cf = tunnels.TunnelManager(8080, tunnel_backend="cloudflare")
        assert tm_cf.start() is True
        assert tm_cf.public_url == "https://cf-direct.trycloudflare.com"

    # 3. Ngrok backend explicitly invokes NgrokTunnel
    fake_ngrok = FakeTunnel(8080, "ngrok", url="https://ngrok-direct.ngrok-free.app", succeeds=True)
    with patch("qrtunnel.tunnels.NgrokTunnel", return_value=fake_ngrok):
        tm_ng = tunnels.TunnelManager(8080, tunnel_backend="ngrok")
        assert tm_ng.start() is True
        assert tm_ng.public_url == "https://ngrok-direct.ngrok-free.app"


def test_broken_pipe_during_send_upload_page():
    handler = create_handler(path="/", method="GET")
    # Simulate broken pipe on wfile.write
    handler.wfile = MagicMock()
    handler.wfile.write.side_effect = BrokenPipeError("Broken pipe")

    # Should not raise exception
    handler.send_upload_page()
    assert handler.close_connection is True


def test_file_transfer_handler_handle_and_finish_catch_broken_pipe():
    from qrtunnel.server import FileTransferHandler

    # Mock instance of FileTransferHandler
    mock_instance = MagicMock(spec=FileTransferHandler)
    mock_instance.wfile = MagicMock()
    mock_instance.wfile.closed = False
    mock_instance.wfile.flush.side_effect = BrokenPipeError("Broken pipe")
    mock_instance.close_connection = False

    # Calling finish with BrokenPipeError on super().finish() should not raise
    with patch(
        "http.server.BaseHTTPRequestHandler.finish", side_effect=BrokenPipeError("Broken pipe")
    ):
        FileTransferHandler.finish(mock_instance)

    # Calling handle with BrokenPipeError on super().handle() should set close_connection
    with patch(
        "http.server.BaseHTTPRequestHandler.handle", side_effect=BrokenPipeError("Broken pipe")
    ):
        FileTransferHandler.handle(mock_instance)
        assert mock_instance.close_connection is True


def test_threading_http_server_handle_error_suppresses_broken_pipe(capsys):
    from qrtunnel.server import ThreadingHTTPServer

    server = MagicMock(spec=ThreadingHTTPServer)

    # Simulate BrokenPipeError in sys.exc_info()
    try:
        raise BrokenPipeError(32, "Broken pipe")
    except BrokenPipeError:
        ThreadingHTTPServer.handle_error(server, None, ("10.12.235.198", 39032))

    captured = capsys.readouterr()
    assert "BrokenPipeError" not in captured.err
    assert "Traceback" not in captured.err


def test_upload_page_contains_xhr_open_and_form_action():
    from qrtunnel.ui.upload import render_upload_page

    html = render_upload_page()
    assert "xhr.open('POST', '/upload', true);" in html
    assert 'action="/upload"' in html
    assert 'id="upload-form"' in html
