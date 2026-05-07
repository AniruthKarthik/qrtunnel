from qrtunnel.config import Config
from qrtunnel.history import load_history, log_transfer


def test_log_transfer_writes_history(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "CONFIG_DIR", tmp_path)

    log_transfer("file.txt", 8, "192.168.1.10", "send")

    entries = load_history()
    assert len(entries) == 1
    assert entries[0]["filename"] == "file.txt"
    assert entries[0]["size"] == 8
    assert entries[0]["client_ip"] == "192.168.1.10"
    assert entries[0]["direction"] == "send"
