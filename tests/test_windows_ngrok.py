import subprocess

from qrtunnel import tunnels


def test_windows_ngrok_hint_uses_winget(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="v1.0", stderr="")

    monkeypatch.setattr(tunnels.platform, "system", lambda: "Windows")
    monkeypatch.setattr(tunnels.subprocess, "run", fake_run)

    assert (
        tunnels.get_windows_ngrok_install_hint() == "Install ngrok with: winget install ngrok.ngrok"
    )


def test_windows_ngrok_hint_falls_back_to_download(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(tunnels.platform, "system", lambda: "Windows")
    monkeypatch.setattr(tunnels.subprocess, "run", fake_run)

    assert (
        tunnels.get_windows_ngrok_install_hint()
        == "Download ngrok from: https://ngrok.com/download"
    )
