"""Bauhaus Security Check / Login Page."""

from .session import render_receiver_session_script
from .theme import BAUHAUS_CSS, ICONS


def render_login_page(error: str = None) -> str:
    error_html = (
        f'<div class="error-banner"><span class="error-pip">!</span> {error}</div>' if error else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>QRTunnel — Security Check</title>
<style>
{BAUHAUS_CSS}

body {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--bh-space-6) var(--bh-space-4);
}}

.login-frame {{
    background: var(--bh-surface);
    border: var(--bh-border-heavy) solid var(--bh-border);
    padding: var(--bh-space-8) var(--bh-space-6);
    max-width: 400px;
    width: 100%;
    text-align: center;
}}

.brand-badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 48px;
    height: 48px;
    background: var(--bh-ink);
    color: var(--bh-surface);
    margin-bottom: var(--bh-space-4);
}}

h1 {{
    font-size: 22px;
    font-weight: 800;
    color: var(--bh-ink);
    text-transform: uppercase;
    letter-spacing: -0.3px;
    margin-bottom: var(--bh-space-1);
}}

.subtitle {{
    font-size: 13.5px;
    color: var(--bh-ink-secondary);
    margin-bottom: var(--bh-space-6);
    line-height: 1.45;
}}

.error-banner {{
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--bh-red-subtle);
    border: 1.5px solid var(--bh-red);
    color: var(--bh-red);
    font-size: 12.5px;
    font-weight: 600;
    padding: 10px 14px;
    margin-bottom: var(--bh-space-5);
    text-align: left;
}}

.error-pip {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    background: var(--bh-red);
    color: #fff;
    font-weight: 800;
    font-size: 11px;
}}

.pin-input {{
    width: 100%;
    padding: 14px;
    background: var(--bh-surface-alt);
    border: var(--bh-border-width) solid var(--bh-border);
    color: var(--bh-ink);
    font-size: 32px;
    font-weight: 800;
    text-align: center;
    letter-spacing: 12px;
    margin-bottom: var(--bh-space-5);
    transition: background 0.12s, border-color 0.12s;
}}

.pin-input:focus {{
    background: var(--bh-surface);
    border-color: var(--bh-blue);
    outline: none;
}}

.submit-btn {{
    width: 100%;
    padding: 14px 20px;
    background: var(--bh-blue);
    color: #FFFFFF;
    border: 1.5px solid var(--bh-ink);
    font-size: 13.5px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background 0.12s ease;
}}

.submit-btn:hover {{
    background: var(--bh-blue-dark);
}}

.submit-btn:active {{
    transform: translateY(1px);
}}

.footer-meta {{
    margin-top: var(--bh-space-6);
    padding-top: var(--bh-space-4);
    border-top: 1px solid var(--bh-border-subtle);
    font-size: 11px;
    color: var(--bh-ink-muted);
    font-weight: 600;
    letter-spacing: 0.06em;
}}
</style>
</head>
<body>
<div class="login-frame">
    <div class="brand-badge">
        {ICONS["lock"]}
    </div>
    <div class="micro-label" style="margin-bottom: 6px;">Security // Access Verification</div>
    <h1>Security Check</h1>
    <p class="subtitle">Enter the 4-digit access code shown on the host computer.</p>
    {error_html}
    <form action="/login" method="post">
        <input type="text" name="password" class="pin-input mono" pattern="[0-9]*" inputmode="numeric"
               placeholder="0000" maxlength="4" required autofocus autocomplete="off">
        <button type="submit" class="submit-btn">Verify Code</button>
    </form>
    <div class="footer-meta mono">QRTUNNEL // SECURE AUTHENTICATION</div>
</div>
{render_receiver_session_script()}
</body>
</html>"""
    return html
