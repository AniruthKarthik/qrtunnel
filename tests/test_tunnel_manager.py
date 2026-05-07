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
