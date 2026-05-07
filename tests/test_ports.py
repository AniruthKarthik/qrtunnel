import pytest

from qrtunnel import utils


class FakeSocket:
    def __init__(self, should_bind=True):
        self.should_bind = should_bind

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def setsockopt(self, *args):
        pass

    def bind(self, address):
        if not self.should_bind:
            raise OSError("in use")


def test_is_port_available_detects_bind_failure(monkeypatch):
    monkeypatch.setattr(utils.socket, "socket", lambda *args: FakeSocket(should_bind=False))

    assert not utils.is_port_available(20000)


def test_find_available_port_returns_bindable_port(monkeypatch):
    monkeypatch.setattr(utils.random, "randint", lambda start, end: 20001)
    monkeypatch.setattr(utils, "is_port_available", lambda port: port == 20001)

    assert utils.find_available_port(20000, 60000, attempts=1) == 20001


def test_find_available_port_raises_after_attempts(monkeypatch):
    monkeypatch.setattr(utils.random, "randint", lambda start, end: 20001)
    monkeypatch.setattr(utils, "is_port_available", lambda port: False)

    with pytest.raises(OSError):
        utils.find_available_port(20000, 60000, attempts=1)
