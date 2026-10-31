import subprocess

from qrtunnel import utils


def test_get_lan_ip_prefers_physical_linux_interface(monkeypatch):
    output = "\n".join(
        [
            "2: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0",
            "3: tun0       inet 10.8.0.2/24 scope global tun0",
            "4: wlan0      inet 192.168.1.44/24 brd 192.168.1.255 scope global wlan0",
        ]
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout=output, stderr="")

    monkeypatch.setattr(utils.platform, "system", lambda: "Linux")
    monkeypatch.setattr(utils.subprocess, "run", fake_run)

    assert utils.get_lan_ip() == "192.168.1.44"


def test_get_lan_ip_prefers_darwin_interface(monkeypatch):
    monkeypatch.setattr(utils.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(utils, "_get_darwin_interface_ips", lambda: ["192.168.1.77"])

    assert utils.get_lan_ip() == "192.168.1.77"


def test_get_lan_ip_falls_back_to_udp_socket(monkeypatch):
    monkeypatch.setattr(utils.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(utils, "_get_darwin_interface_ips", lambda: [])

    class FakeUDPSocket:
        def settimeout(self, timeout):
            pass

        def connect(self, addr):
            pass

        def getsockname(self):
            return ("192.168.1.88", 54321)

        def close(self):
            pass

    monkeypatch.setattr(utils.socket, "socket", lambda *args, **kwargs: FakeUDPSocket())

    assert utils.get_lan_ip() == "192.168.1.88"


def test_get_lan_ip_falls_back_to_hostname(monkeypatch):
    monkeypatch.setattr(utils.platform, "system", lambda: "Linux")
    monkeypatch.setattr(utils, "_get_linux_interface_ips", lambda: [])

    def fake_socket_fail(*args, **kwargs):
        raise OSError("Network unreachable")

    monkeypatch.setattr(utils.socket, "socket", fake_socket_fail)
    monkeypatch.setattr(utils.socket, "gethostname", lambda: "host")
    monkeypatch.setattr(
        utils.socket,
        "gethostbyname_ex",
        lambda hostname: (hostname, [], ["127.0.0.1", "192.168.1.55"]),
    )

    assert utils.get_lan_ip() == "192.168.1.55"
