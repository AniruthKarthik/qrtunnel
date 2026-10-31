"""Bauhaus Upload Complete / Success Page."""

from typing import Any, List, Union

from ..utils import format_size
from .session import render_receiver_session_script
from .theme import BAUHAUS_CSS, ICONS


def render_upload_success_page(files: Union[str, List[Any]]) -> str:
    if isinstance(files, str):
        file_items = [(files, None)]
    elif isinstance(files, list):
        file_items = [
            (item[0], item[1]) if isinstance(item, (tuple, list)) else (str(item), None)
            for item in files
        ]
    else:
        file_items = [(str(files), None)]

    total_files = len(file_items)
    if total_files == 1:
        fn, sz = file_items[0]
        label = f"{fn} ({format_size(sz)})" if sz is not None else fn
        subtitle = "The file was successfully received on the host computer."
        content_html = f'<div class="receipt-single mono">{label}</div>'
        btn_label = "Upload Another File"
    else:
        subtitle = f"{total_files} files were successfully received on the host computer."
        items_html = ""
        for fn, sz in file_items:
            sz_str = (
                f' <span class="mono" style="color:var(--bh-ink-muted);font-weight:500;">({format_size(sz)})</span>'
                if sz is not None
                else ""
            )
            items_html += f'<li class="receipt-item"><span class="receipt-name mono">✓ {fn}</span>{sz_str}</li>'
        content_html = f'<ul class="receipt-list">{items_html}</ul>'
        btn_label = "Upload More Files"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>QRTunnel — Upload Complete</title>
<style>
{BAUHAUS_CSS}

body {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--bh-space-6) var(--bh-space-4);
}}

.success-frame {{
    background: var(--bh-surface);
    border: var(--bh-border-heavy) solid var(--bh-border);
    padding: var(--bh-space-8) var(--bh-space-6);
    max-width: 460px;
    width: 100%;
    text-align: center;
}}

.badge-emblem {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 52px;
    background: var(--bh-green);
    color: #FFFFFF;
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
    line-height: 1.45;
    margin-bottom: var(--bh-space-5);
}}

.receipt-single {{
    display: block;
    background: var(--bh-surface-alt);
    border: var(--bh-border-width) solid var(--bh-border);
    padding: 12px 16px;
    font-size: 13px;
    font-weight: 700;
    color: var(--bh-ink);
    margin-bottom: var(--bh-space-6);
    word-break: break-all;
}}

.receipt-list {{
    list-style: none;
    border: var(--bh-border-width) solid var(--bh-border);
    background: var(--bh-surface-alt);
    margin-bottom: var(--bh-space-6);
    max-height: 220px;
    overflow-y: auto;
    text-align: left;
}}

.receipt-item {{
    padding: 10px 14px;
    border-bottom: 1px solid var(--bh-border-subtle);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--bh-ink);
    word-break: break-all;
}}

.receipt-item:last-child {{
    border-bottom: none;
}}

.receipt-name {{
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 72%;
}}

.action-btn {{
    display: block;
    width: 100%;
    padding: 14px 20px;
    background: var(--bh-blue);
    color: #FFFFFF;
    border: 1.5px solid var(--bh-ink);
    font-size: 13.5px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    text-align: center;
    cursor: pointer;
    transition: background 0.12s ease;
}}

.action-btn:hover {{
    background: var(--bh-blue-dark);
}}

.action-btn:active {{
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
<div class="success-frame">
    <div class="badge-emblem">
        {ICONS["check"]}
    </div>
    <div class="micro-label" style="margin-bottom: 6px;">Transfer // Confirmed</div>
    <h1>Upload Complete</h1>
    <p class="subtitle">{subtitle}</p>
    {content_html}
    <a href="/" class="action-btn">{btn_label}</a>
    <div class="footer-meta mono">QRTUNNEL // RECEIPT RECORDED</div>
</div>
{render_receiver_session_script()}
</body>
</html>"""
    return html
