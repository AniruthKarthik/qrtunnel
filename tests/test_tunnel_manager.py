from qrtunnel import tunnels


class FakeTunnel:
    def __init__(self, local_port, name, succeeds=True):
        self.local_port = local_port
        self.name = name
        self.public_url = f"https://{name}.example"
        self.succeeds = succeeds

    def start(self):
        return self.succeeds

    def stop(self):
        pass


def test_tunnel_manager_lan_only_requires_lan_ip(monkeypatch):
    monkeypatch.setattr(tunnels, "get_lan_ip", lambda: None)

    # When all fallback tunnels also fail, start() returns False
    manager = tunnels.TunnelManager(8000, lan_only=True)
    assert not manager.start()


def test_tunnel_manager_lan_only_switches_when_no_lan_ip(monkeypatch):
    monkeypatch.setattr(tunnels, "get_lan_ip", lambda: None)
    monkeypatch.setattr(
        tunnels, "CloudflareTunnel", lambda port: FakeTunnel(port, "cloudflare", succeeds=True)
    )
    # When LAN IP is absent, switches to public tunnel without error
    manager = tunnels.TunnelManager(8000, lan_only=True, tunnel_backend="cloudflare")
    assert manager.start()
    assert manager.public_url == "https://cloudflare.example"


def test_tunnel_manager_cloudflare_backend(monkeypatch):
    monkeypatch.setattr(tunnels, "get_lan_ip", lambda: "192.168.1.100")
    monkeypatch.setattr(
        tunnels, "CloudflareTunnel", lambda port: FakeTunnel(port, "cloudflare", succeeds=True)
    )

    manager = tunnels.TunnelManager(8000, tunnel_backend="cloudflare")
    assert manager.start()
    assert manager.public_url == "https://cloudflare.example"


def test_ssh_tunnel_regex_pattern():
    import re

    pattern = re.compile(r"https://[a-zA-Z0-9.-]+(?:\.lhr\.life|\.localhost\.run)")
    assert pattern.search("https://abc-123.lhr.life") is not None
    assert pattern.search("https://xyz-456.localhost.run") is not None


def test_tunnel_manager_cloudflare_fallback_to_ssh(monkeypatch):
    monkeypatch.setattr(tunnels, "get_lan_ip", lambda: "192.168.1.100")
    monkeypatch.setattr(
        tunnels, "CloudflareTunnel", lambda port: FakeTunnel(port, "cloudflared", succeeds=False)
    )
    fake_ssh = FakeTunnel(8000, "SSH Tunnel", succeeds=True)
    fake_ssh.public_url = "https://fallback.lhr.life"
    monkeypatch.setattr(tunnels, "SSHTunnel", lambda port: fake_ssh)

    manager = tunnels.TunnelManager(8000, tunnel_backend="cloudflare")
    assert manager.start() is True
    assert manager.public_url == "https://fallback.lhr.life"
    assert manager.active_tunnel.name == "SSH Tunnel"


def test_tunnel_manager_ssh_fallback_to_cloudflare(monkeypatch):
    monkeypatch.setattr(tunnels, "get_lan_ip", lambda: "192.168.1.100")
    monkeypatch.setattr(
        tunnels, "SSHTunnel", lambda port: FakeTunnel(port, "SSH Tunnel", succeeds=False)
    )
    fake_cf = FakeTunnel(8000, "cloudflared", succeeds=True)
    fake_cf.public_url = "https://fallback.trycloudflare.com"
    monkeypatch.setattr(tunnels, "CloudflareTunnel", lambda port: fake_cf)

    manager = tunnels.TunnelManager(8000, tunnel_backend="ssh")
    assert manager.start() is True
    assert manager.public_url == "https://fallback.trycloudflare.com"
    assert manager.active_tunnel.name == "cloudflared"


def test_cloudflare_tunnel_edge_registration_and_failure_detection():
    cf = tunnels.CloudflareTunnel(6969)

    class DummyProc:
        def __init__(self, lines):
            self.lines = list(lines)
            self.idx = 0
            self.stdout = self

        def readline(self):
            if self.idx < len(self.lines):
                line = self.lines[self.idx] + "\n"
                self.idx += 1
                return line
            return ""

        def poll(self):
            return 0 if self.idx >= len(self.lines) else None

    # Test edge registration success
    success_lines = [
        "+--------------------------------------------------------------------------------------------+",
        "|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |",
        "|  https://quick-test-edge.trycloudflare.com                                                |",
        "+--------------------------------------------------------------------------------------------+",
        "INF Starting metrics server on 127.0.0.1:20241/metrics",
        "INF Tunnel connection curve preferences: [X25519MLKEM768 CurveID(65074) CurveP256] connIndex=0 event=0 ip=198.41.192.227",
        "INF Registered tunnel connection connIndex=0 connection=abc-123 location=HYD",
    ]
    cf.process = DummyProc(success_lines)
    cf._read_output()
    assert cf.url_found.is_set()
    assert cf.public_url == "https://quick-test-edge.trycloudflare.com"
    assert cf.connection_registered.is_set()

    # Test edge connection failure detection (port 7844 refused)
    cf_fail = tunnels.CloudflareTunnel(6969)
    fail_lines = [
        "+--------------------------------------------------------------------------------------------+",
        "|  https://fail-test-edge.trycloudflare.com                                                 |",
        "+--------------------------------------------------------------------------------------------+",
        'ERR Unable to establish connection with Cloudflare edge error="DialContext error: dial tcp 198.41.192.67:7844: connect: connection refused"',
    ]
    cf_fail.process = DummyProc(fail_lines)
    cf_fail._read_output()
    assert cf_fail.url_found.is_set()
    assert cf_fail.connection_failed.is_set()
    assert not cf_fail.connection_registered.is_set()
