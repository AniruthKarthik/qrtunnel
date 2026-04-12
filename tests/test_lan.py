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


if __name__ == "__main__":
    test_is_same_lan()
    print("✅ is_same_lan tests passed!")
