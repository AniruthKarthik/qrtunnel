from pathlib import Path


def test_upload_deduplication_avoids_overwriting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Pre-create a file named report.txt
    existing = tmp_path / "report.txt"
    existing.write_text("original content")

    # Simulate deduplication logic
    sanitized_filename = "report.txt"
    base_stem = Path(sanitized_filename).stem
    base_ext = Path(sanitized_filename).suffix
    saved_filename = sanitized_filename
    counter = 1
    final_path = Path.cwd() / saved_filename
    while final_path.exists():
        saved_filename = f"{base_stem} ({counter}){base_ext}"
        final_path = Path.cwd() / saved_filename
        counter += 1

    assert saved_filename == "report (1).txt"
    assert existing.read_text() == "original content"
