import hashlib

from qrtunnel.utils import sha256_file


def test_sha256_file(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_bytes(b"qrtunnel")

    assert sha256_file(path) == hashlib.sha256(b"qrtunnel").hexdigest()
