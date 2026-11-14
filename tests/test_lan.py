from qrtunnel import is_same_lan


def test_is_same_lan():
    # Same /24 subnet
    assert is_same_lan("192.168.1.5", "192.168.1.20")

    # Different /24 subnet (heuristic failure or different LAN)
    assert not is_same_lan("192.168.1.5", "192.168.2.20")

    # Public IP
    assert not is_same_lan("8.8.8.8", "192.168.1.20")

    # Loopback
    assert not is_same_lan("127.0.0.1", "192.168.1.20")

    # Same IP
    assert is_same_lan("192.168.1.20", "192.168.1.20")


def test_is_same_lan_arp_exact_ip_matching(monkeypatch):
    """Verify ARP lookup does not falsely match substring IPs."""
    from unittest.mock import mock_open, patch

    arp_content = (
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "10.0.0.10        0x1         0x2         00:11:22:33:44:55     *        eth0\n"
    )

    monkeypatch.setattr("platform.system", lambda: "Linux")
    with patch("builtins.open", mock_open(read_data=arp_content)):
        assert not is_same_lan("10.0.0.1", "172.16.0.5")
        assert is_same_lan("10.0.0.10", "172.16.0.5")


if __name__ == "__main__":
    test_is_same_lan()
    print("✅ is_same_lan tests passed!")
