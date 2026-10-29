import io
import zipfile

from qrtunnel.server import FileTransferHandler


def test_build_zip_archive_includes_files_and_directory_children(tmp_path):
    single = tmp_path / "single.txt"
    single.write_text("one")
    directory = tmp_path / "docs"
    directory.mkdir()
    nested = directory / "nested.txt"
    nested.write_text("two")

    FileTransferHandler.file_paths = [str(single), str(directory)]

    data = FileTransferHandler.build_zip_archive(FileTransferHandler)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(archive.namelist()) == ["docs/nested.txt", "single.txt"]
        assert archive.read("single.txt") == b"one"
        assert archive.read("docs/nested.txt") == b"two"


def test_build_zip_archive_single_directory(tmp_path):
    directory = tmp_path / "images"
    directory.mkdir()
    pic = directory / "pic.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n")

    FileTransferHandler.file_paths = []
    data = FileTransferHandler.build_zip_archive(FileTransferHandler, file_paths=[str(directory)])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "images/pic.png" in archive.namelist()

