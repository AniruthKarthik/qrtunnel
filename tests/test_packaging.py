from pathlib import Path


def test_requirements_txt_has_no_local_paths_or_editable_artifacts():
    """Ensure requirements.txt contains clean dependency specifications without local paths."""
    req_file = Path(__file__).resolve().parent.parent / "requirements.txt"
    lines = req_file.read_text().splitlines()
    for line in lines:
        line = line.strip()
        assert not line.startswith("file://"), f"Found local file URL in requirements.txt: {line}"
        assert "@ file://" not in line, f"Found local file URL in requirements.txt: {line}"
        assert line != "e==1.4.5", f"Found invalid editable artifact package in requirements.txt: {line}"
