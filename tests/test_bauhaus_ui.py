"""Tests for QRTunnel's Bauhaus UI/UX redesign and design system."""

import io
import json
from unittest.mock import MagicMock

from qrtunnel.config import Config
from qrtunnel.history import log_transfer
from qrtunnel.server import FileTransferHandler
from qrtunnel.ui import (
    render_dashboard,
    render_download_page,
    render_login_page,
    render_receiver_session_script,
    render_upload_page,
    render_upload_success_page,
)


def create_mock_handler(path="/", method="GET", client_ip="127.0.0.1"):
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.path = path
    handler.command = method
    handler.client_address = (client_ip, 54321)
    handler.headers = {"Host": f"127.0.0.1:{Config.LOCAL_PORT}"}
    handler.rfile = io.BytesIO()
    handler.wfile = io.BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.file_paths = []
    handler.upload_mode = False
    handler.authorized_sessions = set()
    handler.server_lan_ip = "192.168.1.100"
    return handler


def test_dashboard_renders_bauhaus_design_tokens():
    """Verify the dashboard renders the complete Bauhaus design system."""
    html = render_dashboard(
        current_lan_ip="192.168.1.100",
        has_lan=True,
        pin_str="4242",
        port_val="6969",
        rec_init_mode="LAN",
        rec_init_url="http://192.168.1.100:6969",
        rec_init_qr_svg="<svg id='test-qr'></svg>",
        cwd_name="workspace",
        initial_state_json="{}",
        default_tab="send",
    )

    # Traditional Bauhaus color tokens
    assert "--bh-bg: #F8F6F0" in html
    assert "--bh-ink: #111215" in html
    assert "--bh-red: #D22626" in html
    assert "--bh-blue: #164785" in html
    assert "--bh-yellow: #E5A110" in html
    assert "--bh-border: #111215" in html

    # Monospace typography classes
    assert ".mono {" in html
    assert "JetBrains Mono" in html

    # Brand emblem and architectural header
    assert "QRTunnel" in html
    assert "v3.7.1" in html
    assert "READY // LAN: 192.168.1.100:6969" in html

    # Segmented navigation tabs
    assert 'id="tab-btn-send"' in html
    assert 'id="tab-btn-receive"' in html
    assert 'id="tab-btn-history"' in html
    assert 'id="tab-btn-settings"' not in html

    # Port input defaults rendered cleanly
    assert '<input type="number" id="port-input" min="1" max="65535" value="6969"' in html
    assert '<input type="number" id="rec-port-input" min="1" max="65535" value="6969"' in html

    # Minimal clean footer without decorative branding
    assert "BAUHAUS DESIGN SYSTEM" not in html
    assert 'id="footer-port-display"' in html

    # 4-Box Access Code Digits
    assert 'id="send-d-0"' in html
    assert 'id="send-d-1"' in html
    assert 'id="send-d-2"' in html
    assert 'id="send-d-3"' in html
    assert 'id="rec-d-0"' in html
    assert 'id="rec-d-1"' in html
    assert 'id="rec-d-2"' in html
    assert 'id="rec-d-3"' in html

    # Real-Time Telemetry Dashboard
    assert 'id="progress-container"' in html
    assert 'id="progress-bar"' in html
    assert 'id="progress-pct"' in html
    assert 'id="progress-speed"' in html
    assert 'id="progress-stats"' in html
    assert 'id="progress-eta"' in html

    # History Panel & Clear Action (Settings removed)
    assert 'id="panel-history"' in html
    assert 'id="panel-settings"' not in html
    assert 'id="history-tbody"' in html
    assert 'clearHistoryLogs' in html


def test_api_history_endpoint(tmp_path):
    """Verify local clients can fetch transfer history over /api/history."""
    Config.CONFIG_DIR = tmp_path
    log_transfer("document_a.pdf", 204800, "192.168.1.50", "receive")
    log_transfer("archive_b.zip", 5242880, "192.168.1.51", "send")

    handler = create_mock_handler(path="/api/history", method="GET")
    handler.do_GET()

    handler.send_response.assert_called_with(200)
    data = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert "history" in data
    assert len(data["history"]) >= 2
    assert data["history"][0]["filename"] == "document_a.pdf"
    assert data["history"][1]["filename"] == "archive_b.zip"


def test_api_history_clear_endpoint(tmp_path):
    """Verify local clients can clear transfer history over /api/history/clear."""
    Config.CONFIG_DIR = tmp_path
    log_transfer("temp_file.bin", 1024, "127.0.0.1", "send")

    handler = create_mock_handler(path="/api/history/clear", method="POST")
    handler.do_POST()

    handler.send_response.assert_called_with(200)
    data = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert data.get("success") is True

    from qrtunnel.history import load_history

    assert len(load_history()) == 0


def test_login_page_bauhaus_design():
    """Verify Security Check login page adheres to Bauhaus design system."""
    html = render_login_page(error="Invalid access code")
    assert "--bh-bg: #F8F6F0" in html
    assert "Security Check" in html
    assert "4-digit access code" in html
    assert 'placeholder="0000"' in html
    assert 'maxlength="4"' in html
    assert "Invalid access code" in html
    assert "Session Closed" in html


def test_upload_page_bauhaus_design():
    """Verify Upload page adheres to Bauhaus design system."""
    html = render_upload_page()
    assert "--bh-bg: #F8F6F0" in html
    assert "Send Files" in html
    assert '<input type="file" id="file-input" name="file" multiple required>' in html
    assert 'id="file-preview-area"' in html
    assert 'id="progress-container"' in html
    assert 'id="submit-btn"' in html
    assert "Session Closed" in html


def test_download_page_bauhaus_design(tmp_path):
    """Verify Download page adheres to Bauhaus design system."""
    f1 = tmp_path / "song.mp3"
    f1.write_bytes(b"ID3" + b"\x00" * 100)
    html = render_download_page([str(f1)])

    assert "--bh-bg: #F8F6F0" in html
    assert "Download Files" in html
    assert "song.mp3" in html
    assert 'class="file-cb"' in html
    assert 'dl-single-btn' in html
    assert 'id="select-all-btn"' in html
    assert 'id="download-selected-btn"' in html
    assert 'id="progress-container"' in html
    assert "Session Closed" in html


def test_success_page_bauhaus_design():
    """Verify Upload Success page renders with Bauhaus aesthetic."""
    html = render_upload_success_page("blueprint.dxf")
    assert "--bh-bg: #F8F6F0" in html
    assert "#f8fafc" in html
    assert "Upload Complete" in html
    assert "blueprint.dxf" in html
    assert "Upload Another File" in html
    assert "Session Closed" in html


def test_session_script_bauhaus_design():
    """Verify session closed script produces Bauhaus overlay."""
    script = render_receiver_session_script()
    assert "Session Closed" in script
    assert "You can safely close this window." in script
    assert "/api/session/status" in script
    assert "/api/receiver/events" in script
    assert "#F8F6F0" in script
