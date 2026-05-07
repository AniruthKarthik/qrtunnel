import pytest

from qrtunnel.app import validate_send_paths


def test_validate_send_paths_resolves_existing_files(tmp_path):
    source = tmp_path / "file.txt"
    source.write_text("data")

    assert validate_send_paths([source]) == [str(source.resolve())]


def test_validate_send_paths_rejects_missing_files(tmp_path):
    with pytest.raises(SystemExit):
        validate_send_paths([tmp_path / "missing.txt"])
