import sys

from qrtunnel.app import parse_args
from qrtunnel.qr import generate_qr_code


def test_parse_no_qr_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["qrtunnel", "send", "photo.jpg", "--no-qr"])

    args, port = parse_args()

    assert args.command == "send"
    assert args.no_qr is True
    assert port == 6969


def test_parse_expire_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["qrtunnel", "receive", "--expire", "30"])

    args, port = parse_args()

    assert args.command == "receive"
    assert args.expire == 30
    assert port == 6969


def test_generate_qr_code_no_qr_skips_ascii_qr(capsys):
    generate_qr_code("https://example.test/share", no_qr=True)

    output = capsys.readouterr().out
    assert "https://example.test/share" in output
    assert "SCAN THIS QR CODE" not in output
