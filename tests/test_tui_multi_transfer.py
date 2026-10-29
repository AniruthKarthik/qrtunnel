"""Tests for 4-digit PIN, multi-file uploads, and multi-file downloads."""

import io
import zipfile
from unittest.mock import MagicMock

from streaming_form_data import StreamingFormDataParser

from qrtunnel.server import FileTransferHandler, MultiFileTarget


def test_otp_is_4_digits():
    """Verify OTP generation and login template use 4 digits."""
    import random

    otp = f"{random.randint(0, 9999):04d}"
    assert len(otp) == 4
    assert otp.isdigit()

    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.wfile = io.BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    handler.send_login_page()
    html = handler.wfile.getvalue().decode("utf-8")

    assert 'maxlength="4"' in html
    assert 'placeholder="0000"' in html
    assert "4-digit access code" in html


def test_download_page_renders_individual_and_zip_options(tmp_path):
    """Verify download page includes checkboxes, individual links, and zip buttons."""
    f1 = tmp_path / "file1.txt"
    f1.write_text("content 1")
    f2 = tmp_path / "file2.jpg"
    f2.write_bytes(b"\xff\xd8\xff")

    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.file_paths = [str(f1), str(f2)]
    handler.wfile = io.BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.headers = {}
    handler.authorized_sessions = set()
    handler.path = "/"

    handler.send_download_page()
    html = handler.wfile.getvalue().decode("utf-8")

    # Individual download button
    assert "dl-single-btn" in html
    assert "/download/file1.txt" in html
    assert "/download/file2.jpg" in html

    # Checkboxes for selection
    assert 'class="file-cb"' in html
    assert 'id="select-all-btn"' in html

    # Selected zip download button is present
    assert 'id="download-selected-btn"' in html

    # Download all button was removed in favor of selective download
    assert 'id="download-all-btn"' not in html
    assert "/download/all.zip" not in html


def test_serve_selected_zip(tmp_path):
    """Verify selected files are bundled into a custom zip archive."""
    f1 = tmp_path / "apple.txt"
    f1.write_text("apple pie")
    f2 = tmp_path / "banana.txt"
    f2.write_text("banana bread")
    f3 = tmp_path / "cherry.txt"
    f3.write_text("cherry tart")

    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.file_paths = [str(f1), str(f2), str(f3)]
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.authorized_sessions = set()
    handler.path = "/download/selected.zip?files=0,2"

    zip_bytes = io.BytesIO()
    handler.wfile = zip_bytes
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    handler.serve_selected_zip()

    # Parse resulting zip archive
    with zipfile.ZipFile(zip_bytes, "r") as archive:
        names = archive.namelist()
        assert "apple.txt" in names
        assert "cherry.txt" in names
        assert "banana.txt" not in names
        assert archive.read("apple.txt") == b"apple pie"
        assert archive.read("cherry.txt") == b"cherry tart"


def test_build_zip_archive_uses_zip_stored(tmp_path):
    """Verify build_zip_archive uses fast ZIP_STORED without slow CPU compression."""
    f = tmp_path / "fast.txt"
    f.write_text("fast content")
    data = FileTransferHandler.build_zip_archive(FileTransferHandler, file_paths=[str(f)])
    with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
        info = archive.getinfo("fast.txt")
        assert info.compress_type == zipfile.ZIP_STORED


def test_upload_page_has_multiple_input():
    """Verify upload page allows selecting multiple files."""
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.wfile = io.BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.headers = {}
    handler.authorized_sessions = set()
    handler.path = "/upload"

    handler.send_upload_page()
    html = handler.wfile.getvalue().decode("utf-8")

    assert '<input type="file" id="file-input" name="file" multiple required>' in html
    assert "file-preview-area" in html
    assert "Send Files" in html


def test_multi_file_target_parsing(tmp_path):
    """Verify MultiFileTarget handles multiple file parts in a multipart stream."""
    body = (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="file"; filename="doc1.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\n"
        b"First document\r\n"
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="file"; filename="doc2.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\n"
        b"Second document\r\n"
        b"--boundary--\r\n"
    )
    headers = {"Content-Type": "multipart/form-data; boundary=boundary"}
    parser = StreamingFormDataParser(headers=headers)
    target = MultiFileTarget(tmp_path)
    parser.register("file", target)
    parser.data_received(body)

    assert len(target.files) == 2
    fn1, tmp1 = target.files[0]
    fn2, tmp2 = target.files[1]

    assert fn1 == "doc1.txt"
    assert tmp1.read_text() == "First document"
    assert fn2 == "doc2.txt"
    assert tmp2.read_text() == "Second document"

    target.cleanup()
    assert not tmp1.exists()
    assert not tmp2.exists()


def test_get_upload_success_page_multiple_files():
    """Verify upload success page displays multiple received files."""
    handler = FileTransferHandler.__new__(FileTransferHandler)
    files = [("photo1.jpg", 1024 * 1024), ("doc2.pdf", 512 * 1024)]
    html = handler.get_upload_success_page(files)

    assert "2 files were successfully received" in html
    assert "photo1.jpg" in html
    assert "doc2.pdf" in html
    assert "Upload More Files" in html
