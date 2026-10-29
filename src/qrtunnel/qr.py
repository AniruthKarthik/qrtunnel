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


def generate_qr_svg(url: str, box_size: int = 6, border: int = 2) -> str:
    """Generate crisp SVG QR code without external image libraries."""
    try:
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=box_size,
            border=border,
        )
        qr.add_data(url)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        dim = len(matrix) * box_size
        rects = []
        for r, row in enumerate(matrix):
            for c, val in enumerate(row):
                if val:
                    x = c * box_size
                    y = r * box_size
                    rects.append(
                        f'<rect x="{x}" y="{y}" width="{box_size}" height="{box_size}" fill="#0f172a"/>'
                    )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" width="200" height="200">'
            f'<rect width="100%" height="100%" fill="#ffffff" rx="8"/>{"".join(rects)}</svg>'
        )
    except Exception:
        return ""
