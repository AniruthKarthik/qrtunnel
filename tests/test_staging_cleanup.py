"""Tests for staging disk cleanup and lifecycle management."""

import json
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
