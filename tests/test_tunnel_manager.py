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

    manager = tunnels.TunnelManager(8000, lan_only=True)

    assert not manager.start()


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
