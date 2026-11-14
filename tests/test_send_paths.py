import pytest

from qrtunnel.app import validate_send_paths


def test_validate_send_paths_resolves_existing_files(tmp_path):
    source = tmp_path / "file.txt"
    source.write_text("data")

    assert validate_send_paths([source]) == [str(source.resolve())]


def test_validate_send_paths_rejects_missing_files(tmp_path):
    with pytest.raises(SystemExit):
        validate_send_paths([tmp_path / "missing.txt"])


def test_parse_args_preserves_numeric_named_existing_files(tmp_path, monkeypatch):
    """Ensure existing files with numeric dash names are not stripped as port shorthand."""
    from qrtunnel.app import parse_args

    numeric_file = tmp_path / "-8080"
    numeric_file.write_text("data")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["qrtunnel", "send", "-8080"])
    args, port = parse_args()
    assert "-8080" in args.files
    assert port == 6969
