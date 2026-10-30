"""
Reproducible performance benchmarking script for QRTunnel.
Measures:
- File download throughput (MB/s)
- Time To First Byte (TTFB)
- Upload throughput (MB/s)
- Directory / Multi-file ZIP download throughput & TTFB
- Concurrent transfer throughput
- Peak memory (RSS) consumption
"""

import http.client
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qrtunnel.config import Config
from qrtunnel.server import FileTransferHandler, ThreadingHTTPServer


def get_peak_rss_mb():
    try:
        import resource
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        # on Linux ru_maxrss is in KB
        return rusage.ru_maxrss / 1024.0
    except Exception:
        return 0.0


def create_test_file(path: Path, size_mb: int):
    # Fast pseudo-random content or repeated blocks
    chunk = os.urandom(1024 * 1024)  # 1 MB chunk
    with open(path, "wb") as f:
        for _ in range(size_mb):
            f.write(chunk)


def create_test_directory(dir_path: Path, num_files: int, size_per_file_mb: int):
    dir_path.mkdir(parents=True, exist_ok=True)
    for i in range(num_files):
        create_test_file(dir_path / f"file_{i:03d}.bin", size_per_file_mb)


class ServerContext:
    def __init__(self, file_paths=None, upload_mode=False):
        self.port = 25432
        self.file_paths = file_paths or []
        self.upload_mode = upload_mode
        self.server = None
        self.thread = None

    def __enter__(self):
        Config.LOCAL_PORT = self.port
        Config.OTP = "1234"
        FileTransferHandler.file_paths = [str(p) for p in self.file_paths]
        FileTransferHandler.upload_mode = self.upload_mode
        FileTransferHandler.server_lan_ip = "127.0.0.1"
        FileTransferHandler.authorized_sessions = set()

        # Find an open port
        for p in range(25432, 25500):
            try:
                self.server = ThreadingHTTPServer(("127.0.0.1", p), FileTransferHandler)
                self.port = p
                Config.LOCAL_PORT = p
                break
            except OSError:
                continue

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1.0)


def benchmark_download_single(port: int, filename: str, expected_size: int):
    url = f"http://127.0.0.1:{port}/download/{urllib.parse.quote(filename)}"
    req = urllib.request.Request(url)
    
    t0 = time.perf_counter()
    resp = urllib.request.urlopen(req)
    ttfb = time.perf_counter() - t0
    
    total_received = 0
    chunk_size = 1024 * 1024
    while True:
        data = resp.read(chunk_size)
        if not data:
            break
        total_received += len(data)
    
    total_time = time.perf_counter() - t0
    resp.close()
    
    assert total_received == expected_size, f"Expected {expected_size}, got {total_received}"
    throughput = (total_received / (1024 * 1024)) / total_time
    return {
        "ttfb": ttfb,
        "total_time": total_time,
        "throughput_mb_s": throughput,
        "size_mb": total_received / (1024 * 1024),
    }


def benchmark_download_zip(port: int, url_path: str):
    url = f"http://127.0.0.1:{port}{url_path}"
    req = urllib.request.Request(url)
    
    t0 = time.perf_counter()
    resp = urllib.request.urlopen(req)
    ttfb = time.perf_counter() - t0
    
    total_received = 0
    chunk_size = 1024 * 1024
    while True:
        data = resp.read(chunk_size)
        if not data:
            break
        total_received += len(data)
    
    total_time = time.perf_counter() - t0
    resp.close()
    
    throughput = (total_received / (1024 * 1024)) / total_time
    return {
        "ttfb": ttfb,
        "total_time": total_time,
        "throughput_mb_s": throughput,
        "size_mb": total_received / (1024 * 1024),
    }


def benchmark_upload(port: int, filepath: Path):
    file_size = filepath.stat().st_size
    filename = filepath.name
    boundary = "----WebKitFormBoundaryBenchmark7MA4YWxkTrZu0gW"
    
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    footer = f"\r\n--{boundary}--\r\n".encode()
    content_length = len(header) + file_size + len(footer)
    
    t0 = time.perf_counter()
    
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.putrequest("POST", "/upload")
    conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
    conn.putheader("Content-Length", str(content_length))
    conn.endheaders()
    
    conn.send(header)
    chunk_size = 1024 * 1024
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            conn.send(chunk)
    conn.send(footer)
    
    resp = conn.getresponse()
    resp_body = resp.read()
    total_time = time.perf_counter() - t0
    conn.close()
    
    assert resp.status == 200, f"Upload failed with {resp.status}: {resp_body}"
    throughput = (file_size / (1024 * 1024)) / total_time
    return {
        "total_time": total_time,
        "throughput_mb_s": throughput,
        "size_mb": file_size / (1024 * 1024),
    }


def benchmark_concurrent_downloads(port: int, filename: str, expected_size: int, concurrency: int = 4):
    results = [None] * concurrency
    
    def worker(idx):
        try:
            results[idx] = benchmark_download_single(port, filename, expected_size)
        except Exception as e:
            results[idx] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall_time = time.perf_counter() - t0
    
    for r in results:
        if isinstance(r, Exception):
            raise r
            
    total_mb = sum(r["size_mb"] for r in results)
    aggregate_throughput = total_mb / wall_time
    avg_ttfb = sum(r["ttfb"] for r in results) / concurrency
    return {
        "concurrency": concurrency,
        "wall_time": wall_time,
        "aggregate_throughput_mb_s": aggregate_throughput,
        "avg_ttfb": avg_ttfb,
    }


def run_full_suite():
    tmp_dir = Path(tempfile.mkdtemp(prefix="qrtunnel_bench_"))
    try:
        print("=" * 70)
        print("QRTUNNEL PERFORMANCE BENCHMARK SUITE")
        print("=" * 70)
        print(f"Platform: {sys.platform}, Python: {sys.version.split()[0]}")
        print(f"Baseline Peak RSS: {get_peak_rss_mb():.1f} MB")
        print("-" * 70)

        # 1. Single File Download Tests (10 MB, 100 MB, 500 MB)
        file_10mb = tmp_dir / "test_10mb.bin"
        file_100mb = tmp_dir / "test_100mb.bin"
        file_500mb = tmp_dir / "test_500mb.bin"
        
        print("Generating test data...")
        create_test_file(file_10mb, 10)
        create_test_file(file_100mb, 100)
        create_test_file(file_500mb, 500)
        print("Test data ready.\n")

        print("--- Single File Download ---")
        with ServerContext(file_paths=[file_10mb, file_100mb, file_500mb]) as ctx:
            r10 = benchmark_download_single(ctx.port, "test_10mb.bin", 10 * 1024 * 1024)
            print(f"  10 MB Download:  {r10['throughput_mb_s']:8.2f} MB/s | TTFB: {r10['ttfb']*1000:6.2f} ms | Time: {r10['total_time']:6.3f}s")
            
            r100 = benchmark_download_single(ctx.port, "test_100mb.bin", 100 * 1024 * 1024)
            print(f" 100 MB Download:  {r100['throughput_mb_s']:8.2f} MB/s | TTFB: {r100['ttfb']*1000:6.2f} ms | Time: {r100['total_time']:6.3f}s")
            
            r500 = benchmark_download_single(ctx.port, "test_500mb.bin", 500 * 1024 * 1024)
            print(f" 500 MB Download:  {r500['throughput_mb_s']:8.2f} MB/s | TTFB: {r500['ttfb']*1000:6.2f} ms | Time: {r500['total_time']:6.3f}s")
            print(f" Peak RSS after download tests: {get_peak_rss_mb():.1f} MB")

        # 2. Directory & Multi-file ZIP Archive Download
        print("\n--- Directory / Multi-file ZIP Archive Download ---")
        zip_dir = tmp_dir / "test_dir"
        create_test_directory(zip_dir, num_files=20, size_per_file_mb=5)  # 100 MB total in 20 files
        
        with ServerContext(file_paths=[zip_dir]) as ctx:
            rz = benchmark_download_zip(ctx.port, f"/download/{urllib.parse.quote(zip_dir.name)}")
            print(f" 100 MB Dir ZIP:   {rz['throughput_mb_s']:8.2f} MB/s | TTFB: {rz['ttfb']*1000:6.2f} ms | Time: {rz['total_time']:6.3f}s | Size: {rz['size_mb']:.1f} MB")
            print(f" Peak RSS after ZIP test: {get_peak_rss_mb():.1f} MB")

        # 3. File Upload Tests
        print("\n--- File Upload (Multipart Form Data) ---")
        upload_target_dir = tmp_dir / "uploads"
        upload_target_dir.mkdir(exist_ok=True)
        orig_cwd = os.getcwd()
        os.chdir(upload_target_dir)
        try:
            with ServerContext(upload_mode=True) as ctx:
                u10 = benchmark_upload(ctx.port, file_10mb)
                print(f"  10 MB Upload:    {u10['throughput_mb_s']:8.2f} MB/s | Time: {u10['total_time']:6.3f}s")
                
                u100 = benchmark_upload(ctx.port, file_100mb)
                print(f" 100 MB Upload:    {u100['throughput_mb_s']:8.2f} MB/s | Time: {u100['total_time']:6.3f}s")
                print(f" Peak RSS after Upload tests: {get_peak_rss_mb():.1f} MB")
        finally:
            os.chdir(orig_cwd)

        # 4. Concurrent Transfers (4 parallel downloads)
        print("\n--- Concurrent Transfers (4 Parallel Downloads of 100 MB) ---")
        with ServerContext(file_paths=[file_100mb]) as ctx:
            rc = benchmark_concurrent_downloads(ctx.port, "test_100mb.bin", 100 * 1024 * 1024, concurrency=4)
            print(f" 4x100 MB Parallel: Agg: {rc['aggregate_throughput_mb_s']:8.2f} MB/s | Wall Time: {rc['wall_time']:6.3f}s | Avg TTFB: {rc['avg_ttfb']*1000:6.2f} ms")
            print(f" Peak RSS after Concurrent test: {get_peak_rss_mb():.1f} MB")

        print("=" * 70)
        print("BENCHMARK COMPLETE")
        print("=" * 70)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_full_suite()
