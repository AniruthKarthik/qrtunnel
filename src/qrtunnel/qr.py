"""Terminal QR code rendering."""

from .config import Config
from .constants import CLR_B, CLR_G, CLR_R, CLR_RST, CLR_Y, DOT, INFO, OK, WRN


# ─────────────────────────────────────────────────────────
#  QR CODE GENERATION  (preserved)
# ─────────────────────────────────────────────────────────
def generate_qr_code(primary_url, fallback_url=None, no_qr=False):
    if no_qr:
        print("\n" + "=" * 60)
        print("qrtunnel access link")
        print("=" * 60)
        print(f"{INFO} URL: {primary_url}")
        if fallback_url:
            print(f"{OK} Fast local link: {fallback_url}")
        if Config.OTP:
            print("-" * 60)
            print(f"🔒 LAN PASSWORD: {CLR_G}{Config.OTP}{CLR_RST} (valid for this session)")
        print("=" * 60 + "\n")
        return

    try:
        import qrcode

        qr = qrcode.QRCode(
            version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=2
        )
        qr.add_data(primary_url)
        qr.make(fit=True)
        print("\n" + "=" * 60)
        if fallback_url:
            print(
                f"  {CLR_G}{DOT} {CLR_Y}{DOT} {CLR_R}{DOT} {CLR_B}{DOT}{CLR_RST}  qrtunnel - Smart mode enabled"
            )
            print("=" * 60)
            qr.print_ascii(invert=True)
            print("=" * 60)
            print(f"{INFO} Internet link: {primary_url}")
            print(f"{OK} Fast local link: {fallback_url}")
            print("(Auto-detects and switches to High Speed if on same Wi-Fi)")
        else:
            print("SCAN THIS QR CODE TO ACCESS THE FILES:")
            print("=" * 60)
            qr.print_ascii(invert=True)
            print("=" * 60)
            print(f"\n{INFO} URL: {primary_url}")
        if Config.OTP:
            print("-" * 60)
            print(f"🔒 LAN PASSWORD: {CLR_G}{Config.OTP}{CLR_RST} (valid for this session)")
            print("-" * 60)
        print("=" * 60 + "\n")
    except ImportError:
        print("\n" + "=" * 60)
        print(f"{WRN} QR code library not installed")
        print("Install with: pip install qrcode")
        print("=" * 60)
        print(f"{OK} Link: {primary_url}")
        if fallback_url:
            print(f"{INFO} Fallback: {fallback_url}")
        print("=" * 60 + "\n")
