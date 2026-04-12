import builtins
import json

import pytest

from qrtunnel import Config, HotspotHelper


def test_hotspot_setup(tmp_path, monkeypatch):
    """
    Test the hotspot configuration setup and QR data generation.
    Uses monkeypatch to mock user input and tmp_path for config storage.
    """

    # Mock Config directory to use temporary path
    config_dir = tmp_path / ".qrtunnel"
    config_file = config_dir / "config.json"

    # We need to monkeypatch Config.CONFIG_DIR and Config.CONFIG_FILE
    monkeypatch.setattr(Config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(Config, "CONFIG_FILE", config_file)

    # Mock input
    # SSID: MyNet
    # Security: 1 (WPA)
    # Password: secret123
    input_values = ["MyNet", "1", "secret123"]
    input_iterator = iter(input_values)

    def mock_input(prompt=""):
        try:
            val = next(input_iterator)
            return val
        except StopIteration:
            return ""

    monkeypatch.setattr(builtins, "input", mock_input)

    h = HotspotHelper()
    h.config_file = config_file  # Ensure instance uses mocked path

    # Run interactive setup
    h.setup_interactive()

    # Verify config file was created
    assert config_file.exists()

    with open(config_file) as f:
        config_data = json.load(f)
        # HotspotHelper saves under 'hotspot' key
        hotspot = config_data.get("hotspot", {})
        assert hotspot["ssid"] == "MyNet"
        assert hotspot["password"] == "secret123"

    # Verify QR string generation
    qr, ssid, pwd = h.get_qr_data()
    assert ssid == "MyNet"
    assert pwd == "secret123"
    assert "WIFI:T:WPA;S:MyNet;P:secret123;" in qr


if __name__ == "__main__":
    pytest.main([__file__])
