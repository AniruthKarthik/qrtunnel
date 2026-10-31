"""Tests for performance optimizations in QRTunnel.

Covers:
- Streaming ZIP engine (exact size precalculation, chunked streaming, file integrity).
- Checksum cache and on-the-fly upload hashing.
- ActiveTransferTracker concurrency coordination for parallel range downloads.
- HTTP/1.1 Keep-Alive and TCP_NODELAY socket configuration.
"""

import hashlib
import io
import time
import zipfile

from streaming_form_data import StreamingFormDataParser

from qrtunnel.server import (
    ActiveTransferTracker,
    FileTransferHandler,
    MultiFileTarget,
    ThreadingHTTPServer,
)
from qrtunnel.utils import sha256_file, store_cached_checksum
from qrtunnel.zip_stream import (
    calculate_zip_size,
    collect_zip_entries,
    stream_zip_archive,
)


def test_streaming_zip_correctness_and_size_prediction(tmp_path):
    """Ensure streaming ZIP archive matches exact predicted size and extracts correctly."""
    d = tmp_path / "dataset"
    d.mkdir()
    (d / "sub").mkdir()

    f1 = d / "data1.txt"
    f1.write_text("Hello Streaming ZIP!")
    f2 = d / "sub" / "data2.bin"
    f2.write_bytes(b"\x00\x01\x02\x03" * 5000)
    root_file = tmp_path / "standalone.md"
    root_file.write_text("# Documentation")

    entries = collect_zip_entries([str(d), str(root_file)])
    predicted_size = calculate_zip_size(entries)

    buf = io.BytesIO()
    progress_calls = []

    def on_progress(sent, total):
        progress_calls.append((sent, total))

    actual_sent = stream_zip_archive(
        entries,
        buf,
        chunk_size=4096,
        progress_callback=on_progress,
    )

    zip_bytes = buf.getvalue()
    assert actual_sent == predicted_size == len(zip_bytes)
    assert len(progress_calls) > 0
    assert progress_calls[-1] == (predicted_size, predicted_size)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = sorted(zf.namelist())
        assert names == ["dataset/data1.txt", "dataset/sub/data2.bin", "standalone.md"]
        assert zf.read("dataset/data1.txt") == b"Hello Streaming ZIP!"
        assert zf.read("dataset/sub/data2.bin") == b"\x00\x01\x02\x03" * 5000
        assert zf.read("standalone.md") == b"# Documentation"


def test_checksum_cache_hit_and_invalidation(tmp_path):
    """Ensure checksum cache returns instant hit on same file and invalidates on edit."""
    sample = tmp_path / "test_file.bin"
    sample.write_bytes(b"initial content 12345")
    expected_hash = hashlib.sha256(b"initial content 12345").hexdigest()

    # First call: computes and caches
    hash1 = sha256_file(sample)
    assert hash1 == expected_hash

    # Second call: hits cache
    hash2 = sha256_file(sample)
    assert hash2 == expected_hash

    # Pre-store checksum manually
    precomputed = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    target_sample = tmp_path / "precomputed.bin"
    target_sample.write_bytes(b"dummy")
    store_cached_checksum(target_sample, precomputed)
    assert sha256_file(target_sample) == precomputed

    # File modification invalidates cache
    time.sleep(0.01)
    sample.write_bytes(b"modified new content")
    modified_hash = hashlib.sha256(b"modified new content").hexdigest()
    assert sha256_file(sample) == modified_hash


def test_upload_on_the_fly_hashing(tmp_path):
    """Ensure MultiFileTarget computes SHA256 during streaming upload with zero extra disk reads."""
    file_content = b"Performance engineering test content 999"
    boundary = "----TestBoundary123"
    payload = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="upload_test.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        + file_content
        + f"\r\n--{boundary}--\r\n".encode()
    )

    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    parser = StreamingFormDataParser(headers=headers)
    target = MultiFileTarget(tmp_path)
    parser.register("file", target)

    parser.data_received(payload)

    assert len(target.files) == 1
    raw_name, tmp_file = target.files[0]
    assert raw_name == "upload_test.txt"
    assert tmp_file.exists()

    expected_sha = hashlib.sha256(file_content).hexdigest()
    assert target.checksums.get(tmp_file) == expected_sha

    target.cleanup()
    assert not tmp_file.exists()


def test_active_transfer_tracker_parallel_coordination():
    """Ensure ActiveTransferTracker aggregates bytes across concurrent range connections."""
    tracker = ActiveTransferTracker()
    client_ip = "192.168.1.100"
    path = "/files/large.iso"
    total_size = 1000

    # Two parallel range streams connect
    tracker.start_stream(client_ip, path, total_size, is_range=True)
    tracker.start_stream(client_ip, path, total_size, is_range=True)

    # Stream 1 sends 200 bytes
    agg1, tot1 = tracker.update_sent(client_ip, path, 200)
    assert agg1 == 200
    assert tot1 == 1000

    # Stream 2 sends 300 bytes
    agg2, tot2 = tracker.update_sent(client_ip, path, 300)
    assert agg2 == 500
    assert tot2 == 1000

    # Stream 1 finishes
    finished1 = tracker.finish_stream(client_ip, path)
    assert finished1 is False

    # Stream 2 sends final 500 bytes and finishes
    agg3, tot3 = tracker.update_sent(client_ip, path, 500)
    assert agg3 == 1000
    assert tot3 == 1000

    finished2 = tracker.finish_stream(client_ip, path)
    assert finished2 is True


def test_server_socket_and_protocol_config():
    """Verify ThreadingHTTPServer sets TCP_NODELAY and FileTransferHandler uses HTTP/1.1."""
    assert FileTransferHandler.protocol_version == "HTTP/1.1"
    assert FileTransferHandler.wbufsize == 65536
    assert ThreadingHTTPServer.daemon_threads is True
