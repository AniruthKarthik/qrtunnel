"""Bauhaus Client Download Page - Remote client downloading files from host."""

import os
from typing import List

from ..utils import format_size
from .session import render_receiver_session_script
from .theme import BAUHAUS_CSS, ICONS


def render_download_page(file_paths: List[str]) -> str:
    file_list_html = ""
    basenames = [os.path.basename(fp) for fp in (file_paths or [])]
    has_duplicates = len(basenames) != len(set(basenames))
    for idx, fp in enumerate(file_paths or []):
        fn = os.path.basename(fp)
        href_path = f"/download/{idx}/{fn}" if has_duplicates else f"/download/{fn}"
        display_name = f"{os.path.basename(os.path.dirname(fp))}/{fn}" if has_duplicates else fn
        size_label = format_size(os.path.getsize(fp)) if os.path.isfile(fp) else "folder"
        file_list_html += f"""<li class="file-item">
  <div class="file-cb-wrap">
    <input type="checkbox" class="file-cb" id="cb-{idx}" data-idx="{idx}" data-name="{fn}">
  </div>
  <label for="cb-{idx}" class="file-info" title="Select {display_name}">
    <span class="file-icon-box">{ICONS["file"]}</span>
    <span class="file-name mono">{display_name}</span>
  </label>
  <div class="file-meta">
    <span class="file-size-badge mono">{size_label}</span>
    <a href="{href_path}" class="dl-single-btn" download title="Download {fn}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    </a>
  </div>
</li>"""

    file_count = len(file_paths or [])
    file_count_str = f"{file_count} {'FILE' if file_count == 1 else 'FILES'}"

    html = (
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>QRTunnel — Download Files</title>
<style>
"""
        + BAUHAUS_CSS
        + """

body {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--bh-space-6) var(--bh-space-4);
}

.download-frame {
    background: var(--bh-surface);
    border: var(--bh-border-heavy) solid var(--bh-border);
    padding: var(--bh-space-8) var(--bh-space-6);
    max-width: 520px;
    width: 100%;
}

@media (max-width: 540px) {
    .download-frame {
        padding: var(--bh-space-6) var(--bh-space-4);
    }
}

.header-block {
    text-align: center;
    margin-bottom: var(--bh-space-6);
}

.brand-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    background: var(--bh-ink);
    color: var(--bh-surface);
    margin-bottom: var(--bh-space-3);
}

h1 {
    font-size: 22px;
    font-weight: 800;
    color: var(--bh-ink);
    text-transform: uppercase;
    letter-spacing: -0.3px;
    margin-bottom: var(--bh-space-1);
}

.subtitle {
    font-size: 13.5px;
    color: var(--bh-ink-secondary);
}

.section-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 8px;
    border-bottom: 1.5px solid var(--bh-border);
    margin-bottom: 12px;
}

.select-btn {
    background: var(--bh-surface-alt);
    color: var(--bh-ink);
    border: 1px solid var(--bh-border);
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    cursor: pointer;
    transition: background 0.12s ease;
}

.select-btn:hover {
    background: var(--bh-surface-sunken);
}

.file-count-badge {
    font-size: 11px;
    font-weight: 700;
    color: var(--bh-blue);
    background: var(--bh-blue-subtle);
    border: 1px solid var(--bh-border-subtle);
    padding: 3px 8px;
}

.file-list {
    list-style: none;
    border: var(--bh-border-width) solid var(--bh-border);
    background: var(--bh-surface);
    margin-bottom: var(--bh-space-5);
    max-height: 260px;
    overflow-y: auto;
}

.file-item {
    border-bottom: 1px solid var(--bh-border-subtle);
    display: flex;
    align-items: center;
    padding: 10px 12px;
    gap: 10px;
}

.file-item:last-child {
    border-bottom: none;
}

.file-cb-wrap {
    display: flex;
    align-items: center;
}

.file-cb {
    width: 17px;
    height: 17px;
    accent-color: var(--bh-blue);
    cursor: pointer;
}

.file-info {
    display: flex;
    align-items: center;
    gap: 8px;
    overflow: hidden;
    min-width: 0;
    flex: 1;
    cursor: pointer;
    user-select: none;
}

.file-icon-box {
    color: var(--bh-ink-muted);
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
}

.file-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--bh-ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.file-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
}

.file-size-badge {
    font-size: 11px;
    font-weight: 600;
    color: var(--bh-ink-secondary);
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border-subtle);
    padding: 2px 7px;
    white-space: nowrap;
}

.dl-single-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border);
    color: var(--bh-ink);
    transition: all 0.12s ease;
}

.dl-single-btn:hover {
    background: var(--bh-blue);
    border-color: var(--bh-blue);
    color: #FFFFFF;
}

.selected-button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    padding: 14px 20px;
    background: var(--bh-green);
    color: #FFFFFF;
    border: 1.5px solid var(--bh-ink);
    font-size: 13.5px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background 0.12s ease;
    margin-top: var(--bh-space-4);
}

.selected-button:hover {
    background: #0F6830;
}

.progress-container {
    display: none;
    background: var(--bh-surface-alt);
    border: var(--bh-border-width) solid var(--bh-border);
    padding: var(--bh-space-4);
    margin-top: var(--bh-space-4);
    text-align: left;
}

.progress-status {
    font-size: 12.5px;
    font-weight: 700;
    color: var(--bh-ink);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.spinner {
    width: 14px;
    height: 14px;
    border: 2px solid var(--bh-border-subtle);
    border-top-color: var(--bh-blue);
    animation: spin 0.75s linear infinite;
    display: inline-block;
    flex-shrink: 0;
}

@keyframes spin { to { transform: rotate(360deg); } }

.progress-bar-bg {
    background: var(--bh-surface-sunken);
    border: 1px solid var(--bh-border);
    height: 10px;
    overflow: hidden;
}

.progress-bar-fill {
    background: var(--bh-blue);
    height: 100%;
    width: 0%;
    transition: width 0.12s linear;
}

.progress-info {
    display: flex;
    justify-content: space-between;
    margin-top: 10px;
    font-size: 11.5px;
    color: var(--bh-ink-secondary);
    font-weight: 600;
}

.footer-meta {
    margin-top: var(--bh-space-6);
    padding-top: var(--bh-space-4);
    border-top: 1px solid var(--bh-border-subtle);
    font-size: 11px;
    color: var(--bh-ink-muted);
    font-weight: 600;
    text-align: center;
    letter-spacing: 0.06em;
}
</style>
</head>
<body>
<div class="download-frame">
    <div class="header-block">
        <div class="brand-badge">
            """
        + ICONS["receive"]
        + """
        </div>
        <div class="micro-label" style="margin-bottom: 6px;">Sender Mode // File Manifest</div>
        <h1>Download Files</h1>
        <p class="subtitle">Download files individually or select files to bundle as a zip</p>
    </div>

    <div class="section-top">
        <div style="display:flex;align-items:center;gap:10px;">
            <button type="button" id="select-all-btn" class="select-btn">Select All</button>
            <span class="micro-label">Available Files</span>
        </div>
        <span class="file-count-badge mono">"""
        + file_count_str
        + """</span>
    </div>

    <ul class="file-list">"""
        + file_list_html
        + """</ul>

    <div id="progress-container" class="progress-container">
        <div class="progress-status" id="progress-status">
            <span class="spinner" id="progress-spinner"></span>
            <span id="progress-status-text">Zipping selected files on host...</span>
        </div>
        <div class="progress-bar-bg">
            <div id="progress-bar" class="progress-bar-fill"></div>
        </div>
        <div class="progress-info mono">
            <span id="progress-pct">0%</span>
            <span id="progress-speed">0 B/s</span>
            <span id="progress-stats">0 B / 0 B</span>
        </div>
    </div>

    <button type="button" id="download-selected-btn" class="selected-button" style="display:none;">
        """
        + ICONS["check"]
        + """
        <span id="selected-btn-text">Download Selected (.zip)</span>
    </button>

    <div class="footer-meta mono">QRTUNNEL // STREAMING ARCHIVE DISPATCH</div>
</div>

<script>
const checkboxes = document.querySelectorAll('.file-cb');
const selectAllBtn = document.getElementById('select-all-btn');
const dlSelectedBtn = document.getElementById('download-selected-btn');
const selectedBtnText = document.getElementById('selected-btn-text');
const progressContainer = document.getElementById('progress-container');
const progressStatusText = document.getElementById('progress-status-text');
const progressSpinner = document.getElementById('progress-spinner');
const progressBar = document.getElementById('progress-bar');
const progressPct = document.getElementById('progress-pct');
const progressSpeed = document.getElementById('progress-speed');
const progressStats = document.getElementById('progress-stats');

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    var kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    var mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + ' MB';
    var gb = mb / 1024;
    return gb.toFixed(1) + ' GB';
}

function updateSelection() {
    var checked = Array.from(checkboxes).filter(cb => cb.checked);
    var count = checked.length;
    if (count > 0) {
        dlSelectedBtn.style.display = 'flex';
        selectedBtnText.textContent = count === 1 ? 'Download Selected (1 file as .zip)' : 'Download Selected (' + count + ' files as .zip)';
    } else {
        dlSelectedBtn.style.display = 'none';
    }
    if (selectAllBtn) {
        selectAllBtn.textContent = count === checkboxes.length ? 'Deselect All' : 'Select All';
    }
}

checkboxes.forEach(cb => {
    cb.addEventListener('change', updateSelection);
});

if (selectAllBtn) {
    selectAllBtn.addEventListener('click', () => {
        var allChecked = Array.from(checkboxes).every(cb => cb.checked);
        checkboxes.forEach(cb => cb.checked = !allChecked);
        updateSelection();
    });
}

if (dlSelectedBtn) {
    dlSelectedBtn.addEventListener('click', () => {
        var selectedIndices = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.getAttribute('data-idx'));
        if (selectedIndices.length === 0) return;

        progressContainer.style.display = 'block';
        progressStatusText.textContent = 'Zipping selected files on host...';
        progressSpinner.style.display = 'inline-block';
        progressBar.style.width = '0%';
        progressPct.textContent = '0%';

        var downloadUrl = '/download/selected.zip?files=' + selectedIndices.join(',');
        var iframe = document.createElement('iframe');
        iframe.style.display = 'none';
        iframe.src = downloadUrl;
        document.body.appendChild(iframe);

        setTimeout(() => {
            progressStatusText.textContent = 'Transfer complete';
            progressSpinner.style.display = 'none';
            progressBar.style.width = '100%';
            progressPct.textContent = '100%';
        }, 3000);
    });
}
</script>
"""
        + render_receiver_session_script()
        + """
</body>
</html>"""
    )
    return html
