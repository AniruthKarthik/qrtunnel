"""Tests for staging disk cleanup and lifecycle management."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qrtunnel.app import main
from qrtunnel.config import Config
from qrtunnel.server import FileTransferHandler
from qrtunnel.sync import (
    SenderSync,
    cleanup_stale_staging_dirs,
    sender_sync,
)


@pytest.fixture
def temp_config_dir(monkeypatch):
    """Fixture providing an isolated temporary CONFIG_DIR for staging tests."""
    temp_dir = tempfile.mkdtemp()
    config_path = Path(temp_dir)
    monkeypatch.setattr(Config, "CONFIG_DIR", config_path)
    monkeypatch.setattr(Config, "CONFIG_FILE", config_path / "config.json")
    yield config_path
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_staging_dir_registration_and_cleanup(temp_config_dir):
    """Verify that staged files in ~/.qrtunnel/staged are completely removed upon cleanup."""
    staging_dir = temp_config_dir / "staged" / "1700000000_abc123"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_file = staging_dir / "sample_video.mp4"
    staged_file.write_bytes(b"A" * 1024 * 1024)  # 1 MB

    sync = SenderSync()
    sync.register_staged_dir(staging_dir)
    sync.file_paths = [str(staged_file)]

    assert staged_file.exists()
    assert staging_dir.exists()

    sync.cleanup_staged_files()

    assert not staged_file.exists()
    assert not staging_dir.exists()
    assert sync.file_paths == []
    assert sync.staged_dirs == []


def test_safety_guard_preserves_user_files(temp_config_dir, tmp_path):
    """Strict security guard: user files outside ~/.qrtunnel/staged MUST NEVER be deleted."""
    user_dir = tmp_path / "user_documents"
    user_dir.mkdir()
    user_file = user_dir / "important_contract.pdf"
    user_file.write_text("Confidential user content")

    sync = SenderSync()
    # Malicious or buggy attempt to register user directory as staging
    sync.register_staged_dir(user_dir)
    sync.file_paths = [str(user_file)]

    sync.cleanup_staged_files()

    # User file must be 100% untouched and preserved
    assert user_file.exists()
    assert user_file.read_text() == "Confidential user content"
    assert sync.file_paths == [str(user_file)]


def test_close_from_browser_triggers_cleanup(temp_config_dir):
    """Closing from browser (beacon/button) must immediately clean up staged files."""
    staging_dir = temp_config_dir / "staged" / "session_browser"
    staging_dir.mkdir(parents=True, exist_ok=True)
    test_file = staging_dir / "data.bin"
    test_file.write_bytes(b"hello")

    sync = SenderSync()
    sync.register_staged_dir(staging_dir)

    sync.close_from_browser()

    assert not staging_dir.exists()
    assert sync.closed_by_browser.is_set()
    assert sync.shutdown_event.is_set()


def test_close_from_terminal_triggers_cleanup(temp_config_dir):
    """Closing from terminal ('q' / Ctrl+C) must immediately clean up staged files."""
    staging_dir = temp_config_dir / "staged" / "session_terminal"
    staging_dir.mkdir(parents=True, exist_ok=True)
    test_file = staging_dir / "data.bin"
    test_file.write_bytes(b"hello")

    sync = SenderSync()
    sync.register_staged_dir(staging_dir)

    sync.close_from_terminal()

    assert not staging_dir.exists()
    assert sync.closed_by_terminal.is_set()
    assert sync.shutdown_event.is_set()


def test_shutdown_all_servers_triggers_cleanup(temp_config_dir):
    """Server shutdown must clean up staged directories."""
    staging_dir = temp_config_dir / "staged" / "session_shutdown"
    staging_dir.mkdir(parents=True, exist_ok=True)
    test_file = staging_dir / "data.bin"
    test_file.write_bytes(b"test")

    sync = SenderSync()
    sync.register_staged_dir(staging_dir)

    sync.shutdown_all_servers()
    assert not staging_dir.exists()


def test_cleanup_stale_staging_dirs_startup_gc(temp_config_dir):
    """Garbage collector sweeps orphaned staging dirs from prior crashed instances."""
    staged_root = temp_config_dir / "staged"

    # 1. Orphaned dir with non-existent PID
    orphan_dir = staged_root / "orphan_1"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / ".owner_pid").write_text("99999999")  # dead pid
    (orphan_dir / "chunk.bin").write_bytes(b"X" * 2048)

    # 2. Active dir with alive PID (mocked alive PID 88888)
    active_dir = staged_root / "active_other_instance"
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / ".owner_pid").write_text("88888")
    (active_dir / "live.bin").write_bytes(b"Y" * 4096)

    def mock_is_pid_alive(pid: int) -> bool:
        return pid == 88888

    with patch("qrtunnel.sync.is_pid_alive", side_effect=mock_is_pid_alive):
        reclaimed = cleanup_stale_staging_dirs(force=False)

    # Orphan must be cleaned, active other instance must NOT be touched
    assert not orphan_dir.exists()
    assert active_dir.exists()
    # 2048 (chunk.bin) + 8 (.owner_pid: "99999999") = 2056 bytes
    assert reclaimed == 2056

    # When force=True (manual clean), everything is cleaned
    reclaimed_forced = cleanup_stale_staging_dirs(force=True)
    assert not active_dir.exists()
    # 4096 (live.bin) + 5 (.owner_pid: "88888") = 4101 bytes
    assert reclaimed_forced == 4101


def test_clean_cli_command(temp_config_dir, capsys):
    """Test `qrtunnel clean` and `qrtunnel clean --all` subcommands."""
    staged_root = temp_config_dir / "staged"
    session_dir = staged_root / "old_session"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "payload.dat").write_bytes(b"Z" * 1024)

    # History file
    history_file = temp_config_dir / "history.json"
    history_file.write_text(json.dumps([{"filename": "test.txt", "size": 100}]))

    with patch("sys.argv", ["qrtunnel", "clean"]):
        main()

    captured = capsys.readouterr()
    assert "Cleaned temporary staged files" in captured.out
    assert not session_dir.exists()
    # History was not requested to be cleared
    assert history_file.exists()
    assert len(json.loads(history_file.read_text())) == 1

    # Now test with --all
    with patch("sys.argv", ["qrtunnel", "clean", "--all"]):
        main()

    captured_all = capsys.readouterr()
    assert "Transfer history cleared" in captured_all.out
    assert json.loads(history_file.read_text()) == []


def test_api_sender_stop_and_close_handlers(temp_config_dir):
    """Verify HTTP endpoints /api/sender/stop and /api/sender/close invoke cleanup."""
    staging_dir = temp_config_dir / "staged" / "http_session"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "file.tmp").write_text("temp data")

    sender_sync.register_staged_dir(staging_dir)
    assert staging_dir.exists()

    handler = MagicMock(spec=FileTransferHandler)
    handler.send_response = MagicMock()
    handler.end_headers = MagicMock()

    # Call stop
    FileTransferHandler.handle_sender_stop(handler)
    assert not staging_dir.exists()
    handler.send_response.assert_called_with(204)


def test_cross_platform_is_subpath_windows():
    """Verify is_subpath correctly handles Windows drive letters, casing, and slash variants."""
    from qrtunnel.sync import is_subpath

    with patch("sys.platform", "win32"):
        parent = Path("C:/Users/Tester/.qrtunnel/staged")
        # Subpath with mixed case and backslashes
        child = Path("c:\\users\\tester\\.qrtunnel\\STAGED\\session1\\file.bin")
        # Directory with prefix trick (staged_malicious is NOT inside staged)
        trick = Path("C:\\Users\\Tester\\.qrtunnel\\staged_other\\file.bin")
        # Outside user path
        user_path = Path("C:\\Users\\Tester\\Downloads\\doc.pdf")

        assert is_subpath(child, parent) is True
        assert is_subpath(trick, parent) is False
        assert is_subpath(user_path, parent) is False
        assert is_subpath(parent, parent) is False


def test_cross_platform_windows_pid_alive():
    """Verify is_pid_alive behaves accurately on Windows using kernel32 APIs."""
    import ctypes as real_ctypes

    from qrtunnel.sync import is_pid_alive

    mock_kernel32 = MagicMock()
    # Case 1: Process alive (STILL_ACTIVE = 259)
    mock_kernel32.OpenProcess.return_value = 1234

    def mock_get_exit_alive(h, ref):
        ref._obj.value = 259
        return True

    mock_kernel32.GetExitCodeProcess.side_effect = mock_get_exit_alive

    mock_ctypes = MagicMock()
    mock_ctypes.windll.kernel32 = mock_kernel32
    mock_ctypes.c_ulong = real_ctypes.c_ulong
    mock_ctypes.byref = real_ctypes.byref

    with patch("sys.platform", "win32"), patch.dict("sys.modules", {"ctypes": mock_ctypes}):
        assert is_pid_alive(42) is True

    # Case 2: Process terminated (exit code 0)
    def mock_get_exit_terminated(h, ref):
        ref._obj.value = 0
        return True

    mock_kernel32.GetExitCodeProcess.side_effect = mock_get_exit_terminated
    with patch("sys.platform", "win32"), patch.dict("sys.modules", {"ctypes": mock_ctypes}):
        assert is_pid_alive(42) is False

    # Case 3: Process does not exist (OpenProcess returns 0 / None)
    mock_kernel32.OpenProcess.return_value = 0
    with patch("sys.platform", "win32"), patch.dict("sys.modules", {"ctypes": mock_ctypes}):
        assert is_pid_alive(42) is False


def test_remove_dir_force_handles_readonly(tmp_path):
    """Verify remove_dir_force deletes directories even with read-only files (Windows protection)."""
    import stat

    from qrtunnel.sync import remove_dir_force

    target_dir = tmp_path / "locked_dir"
    target_dir.mkdir()
    locked_file = target_dir / "read_only.txt"
    locked_file.write_text("protected content")
    # Make file read-only
    os.chmod(locked_file, stat.S_IREAD)

    remove_dir_force(target_dir)
    assert not target_dir.exists()


def test_end_to_end_web_ui_transfer_and_cleanup(temp_config_dir):
    """End-to-end integration test: Multipart Web UI upload, download, and stop cleanup."""
    import http.client
    import threading

    from qrtunnel.server import ThreadingHTTPServer
    from qrtunnel.utils import get_lan_ip

    test_port = 19123
    Config.LOCAL_PORT = test_port
    Config.OTP = "9876"
    FileTransferHandler.server_lan_ip = get_lan_ip()
    FileTransferHandler.file_paths = None
    FileTransferHandler.upload_mode = False

    server = ThreadingHTTPServer(("127.0.0.1", test_port), FileTransferHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sender_sync.initialize(port=test_port, pin="9876", lan_ip=get_lan_ip())
    sender_sync.register_server(server)

    try:
        # 1. Share a 512KB payload via Web UI
        payload = b"QRTUNNEL_TEST_DATA_" * (32 * 1024)
        boundary = "----TestBoundaryCrossPlatform"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="payload.bin"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + payload
            + f"\r\n--{boundary}--\r\n".encode()
        )

        conn = http.client.HTTPConnection("127.0.0.1", test_port)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        }
        conn.request("POST", "/api/sender/share?mode=LAN", body=body, headers=headers)
        resp = conn.getresponse()
        assert resp.status == 200
        resp.read()

        # Verify staged file exists
        staged_root = temp_config_dir / "staged"
        staged_dirs = [d for d in staged_root.iterdir() if d.is_dir()]
        assert len(staged_dirs) == 1
        staged_file = staged_dirs[0] / "payload.bin"
        assert staged_file.exists()
        assert staged_file.stat().st_size == len(payload)

        # 2. Authenticate and download file as client
        conn.request(
            "POST",
            "/login",
            body="password=9876",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        login_resp = conn.getresponse()
        cookie = login_resp.getheader("Set-Cookie")
        login_resp.read()

        conn.request("GET", "/download/payload.bin", headers={"Cookie": cookie} if cookie else {})
        dl_resp = conn.getresponse()
        assert dl_resp.status == 200
        downloaded = dl_resp.read()
        assert downloaded == payload

        # 3. Stop transfer via /api/sender/stop
        conn.request("POST", "/api/sender/stop")
        stop_resp = conn.getresponse()
        assert stop_resp.status == 204
        stop_resp.read()

        # 4. Verify staged directory was immediately cleaned up
        remaining = [d for d in staged_root.iterdir() if d.is_dir()]
        assert len(remaining) == 0

    finally:
        server.shutdown()
        server.server_close()
