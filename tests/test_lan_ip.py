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


def test_get_lan_ip_falls_back_to_hostname(monkeypatch):
    monkeypatch.setattr(utils.platform, "system", lambda: "Linux")
    monkeypatch.setattr(utils, "_get_linux_interface_ips", lambda: [])
    monkeypatch.setattr(utils.socket, "gethostname", lambda: "host")
    monkeypatch.setattr(
        utils.socket,
        "gethostbyname_ex",
        lambda hostname: (hostname, [], ["127.0.0.1", "192.168.1.55"]),
    )

    assert utils.get_lan_ip() == "192.168.1.55"
