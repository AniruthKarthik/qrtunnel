import pytest

from qrtunnel.app import validate_receive_destination


def test_validate_receive_destination_creates_missing_dir(tmp_path):
    destination = tmp_path / "uploads" / "nested"

    resolved = validate_receive_destination(destination)

    assert destination.is_dir()
    assert resolved == str(destination.resolve())


def test_validate_receive_destination_rejects_file(tmp_path):
    destination = tmp_path / "not-a-dir"
    destination.write_text("x")

    with pytest.raises(SystemExit):
        validate_receive_destination(destination)
