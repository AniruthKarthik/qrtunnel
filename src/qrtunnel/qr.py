"""Terminal QR code rendering."""

from .config import Config
from .constants import CLR_G, CLR_RST, INFO, OK, WRN


# ─────────────────────────────────────────────────────────
#  QR CODE GENERATION  (preserved)
# ─────────────────────────────────────────────────────────
def generate_qr_code(url, fallback_url=None, no_qr=False):
    target_url = url
    if no_qr:
        print("\n" + "=" * 60)
        print("qrtunnel access link")
        print("=" * 60)
        print(f"{INFO} URL: {target_url}")
        if Config.OTP:
            print("-" * 60)
            print(f"🔒 ACCESS CODE: {CLR_G}{Config.OTP}{CLR_RST} (valid for this session)")
        print("=" * 60 + "\n")
        return

    try:
        import qrcode

        qr = qrcode.QRCode(
            version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=2
        )
        qr.add_data(target_url)
        qr.make(fit=True)
        print("\n" + "=" * 60)
        print("SCAN THIS QR CODE TO ACCESS THE FILES:")
        print("=" * 60)
        qr.print_ascii(invert=True)
        print("=" * 60)
        print(f"\n{INFO} URL: {target_url}")
        if Config.OTP:
            print("-" * 60)
            print(f"🔒 ACCESS CODE: {CLR_G}{Config.OTP}{CLR_RST} (valid for this session)")
            print("-" * 60)
        print("=" * 60 + "\n")
    except ImportError:
        print("\n" + "=" * 60)
        print(f"{WRN} QR code library not installed")
        print("Install with: pip install qrcode")
        print("=" * 60)
        print(f"{OK} Link: {target_url}")
        print("=" * 60 + "\n")
