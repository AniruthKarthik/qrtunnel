import urllib.request

import qrtunnel.utils
from qrtunnel.server import FileTransferHandler
from qrtunnel.utils import get_public_ip


def test_get_public_ip(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b"203.0.113.195\n"

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=2.0: FakeResponse())

    # Reset cached ip
    qrtunnel.utils._CACHED_PUBLIC_IP = None

    ip = get_public_ip()
    assert ip == "203.0.113.195"


def test_check_auth_with_valid_auth_query_token():
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.client_address = ("192.168.1.55", 54321)
    handler.path = "/?auth=secret-transfer-token-123"
    handler.headers = {}
    FileTransferHandler.authorized_sessions = {"secret-transfer-token-123"}

    assert handler.check_auth() is True


def test_check_auth_with_invalid_auth_query_token():
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.client_address = ("192.168.1.55", 54321)
    handler.path = "/?auth=invalid-token"
    handler.headers = {}
    FileTransferHandler.authorized_sessions = {"secret-transfer-token-123"}

    assert handler.check_auth() is False
