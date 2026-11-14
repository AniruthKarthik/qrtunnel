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


def test_is_same_network_ipv4(monkeypatch):
    qrtunnel.utils._CACHED_PUBLIC_IP = "203.0.113.195"
    from qrtunnel.utils import is_same_network

    # Client matching public WAN IP
    assert is_same_network("203.0.113.195", "192.168.1.5") is True
    # Client with different public IP
    assert is_same_network("198.51.100.22", "192.168.1.5") is False
    # Direct LAN client
    assert is_same_network("192.168.1.88", "192.168.1.5") is True


def test_is_same_network_ipv6(monkeypatch):
    import ipaddress

    monkeypatch.setattr(
        qrtunnel.utils,
        "get_host_ipv6_subnets",
        lambda: [ipaddress.ip_network("2401:4900:cade:b472::/64", strict=False)],
    )
    from qrtunnel.utils import is_same_network

    # Matching IPv6 /64 prefix
    assert is_same_network("2401:4900:cade:b472:1234:5678:9abc:def0", "192.168.1.5") is True
    # Different IPv6 subnet
    assert is_same_network("2606:4700:4700::1111", "192.168.1.5") is False


def test_is_tunnel_request():
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.headers = {"CF-Connecting-IP": "203.0.113.195"}
    assert handler.is_tunnel_request() is True

    handler.headers = {}
    assert handler.is_tunnel_request() is False


def test_check_auth_rejects_unauthenticated_tunnel_request():
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.client_address = ("127.0.0.1", 54321)
    handler.path = "/download/secret.pdf"
    handler.headers = {"CF-Connecting-IP": "203.0.113.195"}
    FileTransferHandler.authorized_sessions = set()
    assert handler.check_auth() is False


def test_is_local_request_rejects_tunnel_forwarded_traffic():
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.client_address = ("127.0.0.1", 54321)
    handler.headers = {"X-Forwarded-For": "198.51.100.1"}
    handler.public_url = None
    assert handler.is_local_request() is False

    handler.headers = {}
    assert handler.is_local_request() is True


def test_get_upload_success_page_light_theme():
    handler = FileTransferHandler.__new__(FileTransferHandler)
    html = handler.get_upload_success_page("document.pdf")
    assert "document.pdf" in html
    assert "#f8fafc" in html  # Light theme background
    assert "Upload Complete" in html


def test_get_real_client_ip_validates_ip_format():
    handler = FileTransferHandler.__new__(FileTransferHandler)
    handler.client_address = ("127.0.0.1", 54321)

    # Valid IPv4 and IPv6 forwarded headers
    handler.headers = {"X-Forwarded-For": "203.0.113.195, 10.0.0.1"}
    assert handler.get_real_client_ip() == "203.0.113.195"

    handler.headers = {"CF-Connecting-IP": "2001:db8::1"}
    assert handler.get_real_client_ip() == "2001:db8::1"

    # Malicious XSS or non-IP input in header must be rejected and fall back to socket IP
    handler.headers = {"X-Forwarded-For": "<script>alert(1)</script>"}
    assert handler.get_real_client_ip() == "127.0.0.1"
