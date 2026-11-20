from pathlib import Path


def test_requirements_txt_has_no_local_paths_or_editable_artifacts():
    """Ensure requirements.txt contains clean dependency specifications without local paths."""
    req_file = Path(__file__).resolve().parent.parent / "requirements.txt"
    lines = req_file.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        assert not line.startswith("file://"), f"Found local file URL in requirements.txt: {line}"
        assert "@ file://" not in line, f"Found local file URL in requirements.txt: {line}"
        assert line != "e==1.4.5", (
            f"Found invalid editable artifact package in requirements.txt: {line}"
        )


def test_pyproject_toml_configures_pythonpath_src():
    """Ensure pyproject.toml defines pythonpath = ['src'] for clean out-of-tree test execution."""
    pyproject_file = Path(__file__).resolve().parent.parent / "pyproject.toml"
    content = pyproject_file.read_text(encoding="utf-8")
    assert 'pythonpath = ["src"]' in content


def test_version_consistency_across_metadata_and_docs():
    """Ensure SECURITY.md and DESIGN.md match current version in constants.py and pyproject.toml."""
    from qrtunnel.constants import __version__

    assert __version__ == "3.8.6"

    security_file = Path(__file__).resolve().parent.parent / "SECURITY.md"
    assert "3.8.x" in security_file.read_text(encoding="utf-8")

    design_file = Path(__file__).resolve().parent.parent / "DESIGN.md"
    assert "v3.8.6" in design_file.read_text(encoding="utf-8")
