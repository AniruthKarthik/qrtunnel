"""Bauhaus Host Dashboard - Complete unified Send, Receive, History, and Settings interface."""

from ..constants import __version__
from .theme import BAUHAUS_CSS, ICONS


def render_dashboard(
    current_lan_ip: str,
    has_lan: bool,
    pin_str: str,
    port_val: str,
    rec_init_mode: str,
    rec_init_url: str,
    rec_init_qr_svg: str,
    cwd_name: str,
    initial_state_json: str,
    default_tab: str = "send",
) -> str:
    pin_padded = pin_str.ljust(4, "-")
    pin_d0, pin_d1, pin_d2, pin_d3 = pin_padded[0], pin_padded[1], pin_padded[2], pin_padded[3]

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>qrtunnel - Sender & Receiver — Bauhaus Edition</title>
<style>
""" + BAUHAUS_CSS + """

body {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    padding: 24px 16px;
    background-color: var(--bh-bg);
}

/* Master Layout Frame */
.app-frame {
    background: var(--bh-surface);
    border: var(--bh-border-heavy) solid var(--bh-border);
    max-width: 920px;
    width: 100%;
    display: flex;
    flex-direction: column;
}

/* Top Bauhaus Header Bar */
.top-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px;
    border-bottom: var(--bh-border-heavy) solid var(--bh-border);
    background: var(--bh-surface);
    flex-wrap: wrap;
    gap: 12px;
}

.brand-unit {
    display: flex;
    align-items: center;
    gap: 12px;
}

.brand-emblem-box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    background: #FFFFFF;
    border: var(--bh-border-width) solid var(--bh-border);
    padding: 2px;
    box-sizing: border-box;
    text-decoration: none;
    cursor: pointer;
    transition: border-color 0.12s ease, transform 0.12s ease;
}

.brand-emblem-box:hover {
    border-color: var(--bh-red);
    transform: scale(1.06);
}

.brand-emblem-box svg {
    display: block;
    width: 100%;
    height: 100%;
}

.brand-name {
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--bh-ink);
}

.version-tag {
    font-size: 10px;
    font-weight: 700;
    color: var(--bh-ink-muted);
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border-subtle);
    padding: 2px 6px;
    letter-spacing: 0.04em;
}

.system-status {
    display: inline-flex;
    align-items: center;
    font-size: 11px;
    font-weight: 600;
    color: var(--bh-ink-secondary);
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border-subtle);
    padding: 4px 10px;
    letter-spacing: 0.04em;
}

/* Architectural Segmented Tabs */
.nav-row {
    display: flex;
    border-bottom: var(--bh-border-heavy) solid var(--bh-border);
    background: var(--bh-surface-alt);
}

.nav-tab {
    flex: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 12px 14px;
    border: none;
    border-right: 1px solid var(--bh-border);
    background: transparent;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--bh-ink-secondary);
    cursor: pointer;
    transition: all 0.12s ease;
    user-select: none;
}

.nav-tab:last-child {
    border-right: none;
}

.nav-tab:hover {
    background: var(--bh-surface);
    color: var(--bh-ink);
}

.nav-tab.active {
    background: var(--bh-ink);
    color: #FFFFFF;
}

.nav-tab.active svg {
    stroke: #FFFFFF;
}

/* Panels */
.main-view-panel {
    display: none;
    padding: 0;
}
.main-view-panel.active {
    display: block;
}

/* 2-Column Asymmetric Grid Layout for Send & Receive */
.workspace-grid {
    display: grid;
    grid-template-columns: 1.15fr 0.85fr;
    min-height: 520px;
}

@media (max-width: 768px) {
    .workspace-grid {
        grid-template-columns: 1fr;
    }
}

.pane-primary {
    padding: 24px 22px;
    border-right: var(--bh-border-heavy) solid var(--bh-border);
    display: flex;
    flex-direction: column;
}

@media (max-width: 768px) {
    .pane-primary {
        border-right: none;
        border-bottom: var(--bh-border-heavy) solid var(--bh-border);
    }
}

.pane-stage {
    padding: 24px 22px;
    background: var(--bh-surface-alt);
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    align-items: stretch;
}

/* Typography & Section Titles */
.pane-header {
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--bh-border-subtle);
}

.pane-header h1 {
    font-size: 20px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: -0.3px;
    color: var(--bh-ink);
    margin-bottom: 2px;
}

.pane-header .subtitle {
    font-size: 13px;
    color: var(--bh-ink-secondary);
}

/* Geometric Staging / Dropzone */
.dropzone {
    position: relative;
    border: 2px dashed var(--bh-border);
    background: var(--bh-surface);
    padding: 28px 16px;
    text-align: center;
    cursor: pointer;
    transition: background 0.12s, border-color 0.12s;
    margin-bottom: 16px;
}

.dropzone:hover, .dropzone.dragover {
    background: var(--bh-blue-subtle);
    border-color: var(--bh-blue);
}

#file-input {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    opacity: 0;
    cursor: pointer;
}

.dropzone-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border);
    margin-bottom: 10px;
    color: var(--bh-ink);
}

.dropzone-title {
    font-size: 13.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--bh-ink);
    margin-bottom: 3px;
}

.dropzone-hint {
    font-size: 12px;
    color: var(--bh-ink-muted);
}

/* File Manifest Table */
.manifest-box {
    margin-bottom: 18px;
    border: var(--bh-border-width) solid var(--bh-border);
    background: var(--bh-surface);
}

.manifest-topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bh-surface-alt);
    border-bottom: 1px solid var(--bh-border);
}

.file-count-chip {
    font-size: 11px;
    font-weight: 700;
    color: var(--bh-blue);
    background: var(--bh-blue-subtle);
    border: 1px solid var(--bh-border-subtle);
    padding: 2px 7px;
}

.clear-btn {
    background: none;
    border: none;
    color: var(--bh-red);
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    cursor: pointer;
    padding: 2px 4px;
}

.clear-btn:hover {
    text-decoration: underline !important;
}

.manifest-list {
    list-style: none;
    max-height: 150px;
    overflow-y: auto;
}

.manifest-list li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-bottom: 1px solid var(--bh-border-subtle);
    font-size: 12.5px;
    gap: 8px;
}

.manifest-list li:last-child {
    border-bottom: none;
}

.manifest-item-left {
    display: flex;
    align-items: center;
    gap: 8px;
    overflow: hidden;
    min-width: 0;
    flex: 1;
}

.manifest-name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--bh-ink);
}

.manifest-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
}

.manifest-size {
    font-size: 11px;
    font-weight: 600;
    color: var(--bh-ink-muted);
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border-subtle);
    padding: 1px 6px;
    white-space: nowrap;
}

.remove-btn {
    background: none;
    border: none;
    color: var(--bh-ink-muted);
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    line-height: 1;
    padding: 0 4px;
}

.remove-btn:hover {
    color: var(--bh-red);
}

.manifest-footer {
    padding: 6px 12px;
    background: var(--bh-surface-alt);
    border-top: 1px solid var(--bh-border-subtle);
    font-size: 11.5px;
    font-weight: 700;
    color: var(--bh-ink-secondary);
    text-align: right;
}

/* Tunnel Mode Selector: Modular 4-Tile Grid */
.control-section {
    margin-top: auto;
    padding-top: 14px;
}

.control-header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.port-input-wrap {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: var(--bh-surface);
    border: 1px solid var(--bh-border);
    padding: 2px 4px 2px 6px;
}

.port-label {
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    color: var(--bh-ink-secondary);
    letter-spacing: 0.06em;
}

.port-field {
    width: 58px;
    padding: 2px 4px;
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border-subtle);
    font-size: 12px;
    font-weight: 700;
    color: var(--bh-ink);
    text-align: center;
}

.port-field:focus {
    border-color: var(--bh-blue);
}

.port-btn {
    padding: 3px 8px;
    background: var(--bh-ink);
    color: #FFFFFF;
    border: none;
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    cursor: pointer;
    transition: background 0.12s;
}

.port-btn:hover {
    background: var(--bh-blue);
}

.mode-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
    margin-bottom: 12px;
}

.mode-tile {
    background: var(--bh-surface);
    border: var(--bh-border-width) solid var(--bh-border);
    padding: 10px 4px;
    text-align: center;
    cursor: pointer;
    transition: all 0.12s ease;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    user-select: none;
}

.mode-tile:hover {
    background: var(--bh-surface-alt);
}

.mode-tile.selected, .mode-tile.active {
    background: var(--bh-ink);
    color: #FFFFFF;
}

.mode-tile.selected .mode-tile-title, .mode-tile.active .mode-tile-title {
    color: #FFFFFF;
}

.mode-tile.selected .mode-tile-sub, .mode-tile.active .mode-tile-sub {
    color: var(--bh-yellow);
}

.mode-tile-title {
    font-size: 11.5px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--bh-ink);
    line-height: 1.2;
}

.mode-tile-sub {
    font-size: 9.5px;
    font-weight: 600;
    color: var(--bh-ink-muted);
    margin-top: 3px;
    text-transform: uppercase;
}

.mode-tile input[type="radio"] {
    display: none;
}

.notice-box {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--bh-blue);
    background: var(--bh-blue-subtle);
    border: 1px solid var(--bh-blue);
    padding: 8px 12px;
    margin-bottom: 12px;
    line-height: 1.4;
}

/* Primary Action CTA */
.cta-button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    padding: 13px 20px;
    background: var(--bh-blue);
    color: #FFFFFF;
    border: 1.5px solid var(--bh-ink);
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background 0.12s ease;
    opacity: 0.4;
    pointer-events: none;
}

.cta-button.enabled {
    opacity: 1;
    pointer-events: auto;
}

.cta-button.enabled:hover {
    background: var(--bh-blue-dark);
}

.cta-button.enabled:active {
    transform: translateY(1px);
}

/* Destructive Stop / Close Button */
.stop-button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    padding: 11px 16px;
    background: var(--bh-surface);
    color: var(--bh-red);
    border: 1.5px solid var(--bh-red);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.12s ease;
    margin-top: 14px;
}

.stop-button:hover {
    background: var(--bh-red);
    color: #FFFFFF;
}

/* ── STAGE COLUMN: QR MONOLITH, ACCESS CODE & TELEMETRY ── */
.stage-card {
    background: var(--bh-surface);
    border: var(--bh-border-heavy) solid var(--bh-border);
    padding: 18px 16px;
    text-align: center;
    position: relative;
    margin-bottom: 16px;
}

.qr-monolith {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: #FFFFFF;
    border: 2px solid var(--bh-ink);
    padding: 12px;
    margin-bottom: 10px;
}

/* Bauhaus Corner Registration Marks */
.qr-monolith::before, .qr-monolith::after {
    content: "";
    position: absolute;
    width: 8px;
    height: 8px;
    border-color: var(--bh-ink);
    border-style: solid;
    pointer-events: none;
}
.qr-monolith::before {
    top: -4px;
    left: -4px;
    border-width: 2px 0 0 2px;
}
.qr-monolith::after {
    bottom: -4px;
    right: -4px;
    border-width: 0 2px 2px 0;
}

.qr-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 180px;
    height: 180px;
}

.qr-wrapper svg {
    width: 100%;
    height: 100%;
    display: block;
}

.scan-prompt {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--bh-ink-secondary);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 14px;
}

/* 4-Box Access Code */
.access-code-block {
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border);
    padding: 12px 14px;
    margin-bottom: 12px;
    text-align: center;
}

.access-code-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.access-code-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--bh-ink);
}

.access-code-sub {
    font-size: 10px;
    color: var(--bh-ink-muted);
    font-weight: 600;
}

.digit-boxes {
    display: flex;
    justify-content: center;
    gap: 8px;
}

.digit-box {
    width: 44px;
    height: 52px;
    background: var(--bh-surface);
    border: 2px solid var(--bh-ink);
    font-size: 26px;
    font-weight: 800;
    color: var(--bh-ink);
    display: flex;
    align-items: center;
    justify-content: center;
}

.pin-hidden {
    display: none !important;
}

/* URL Bar */
.url-strip {
    display: flex;
    align-items: center;
    background: var(--bh-surface);
    border: 1px solid var(--bh-border);
    padding: 4px 4px 4px 10px;
    gap: 8px;
}

.url-strip svg {
    color: var(--bh-ink-muted);
    flex-shrink: 0;
}

.url-text {
    font-size: 11.5px;
    font-weight: 700;
    color: var(--bh-blue);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: left;
    flex: 1;
}

.copy-btn {
    background: var(--bh-ink);
    color: #FFFFFF;
    border: none;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background 0.12s;
    flex-shrink: 0;
}

.copy-btn:hover {
    background: var(--bh-blue);
}

/* Loading Overlay for Mode Switching */
.loading-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(248, 246, 240, 0.94);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    z-index: 10;
}

.spinner {
    width: 24px;
    height: 24px;
    border: 2.5px solid var(--bh-border-subtle);
    border-top-color: var(--bh-ink);
    animation: spin 0.75s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* Real-Time Telemetry Dashboard */
.telemetry-card {
    background: var(--bh-surface);
    border: var(--bh-border-heavy) solid var(--bh-border);
    padding: 14px 16px;
    text-align: left;
}

.telemetry-status-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    font-size: 12px;
    font-weight: 700;
    color: var(--bh-ink);
}

.progress-track {
    background: var(--bh-surface-sunken);
    border: 1px solid var(--bh-border);
    height: 10px;
    overflow: hidden;
    margin-bottom: 12px;
}

.progress-bar-fill {
    background: var(--bh-blue);
    height: 100%;
    width: 0%;
    transition: width 0.12s linear;
}

.telemetry-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border-subtle);
    padding: 10px;
}

.tele-cell {
    display: flex;
    flex-direction: column;
}

.tele-label {
    font-size: 9.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--bh-ink-muted);
    margin-bottom: 2px;
}

.tele-val {
    font-size: 12px;
    font-weight: 700;
    color: var(--bh-ink);
}

/* Incoming Transfers (Receive View) */
.incoming-card {
    border: var(--bh-border-width) solid var(--bh-border);
    background: var(--bh-surface);
    margin-bottom: 16px;
}

.incoming-topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bh-surface-alt);
    border-bottom: 1px solid var(--bh-border);
}

.empty-state {
    padding: 32px 16px;
    text-align: center;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--bh-ink-muted);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
}

.empty-state svg {
    color: var(--bh-ink-faint);
}

/* ── HISTORY VIEW ── */
.history-container {
    padding: 24px;
}

.history-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    flex-wrap: wrap;
    gap: 12px;
}

.history-filters {
    display: flex;
    gap: 4px;
}

.filter-btn {
    background: var(--bh-surface-alt);
    border: 1px solid var(--bh-border);
    padding: 5px 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    cursor: pointer;
}

.filter-btn.active {
    background: var(--bh-ink);
    color: #FFFFFF;
}

.clear-history-btn {
    background: transparent;
    border: 1px solid var(--bh-border);
    padding: 5px 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    cursor: pointer;
    color: var(--bh-red);
    margin-left: 8px;
    transition: background 0.1s ease, color 0.1s ease;
}

.clear-history-btn:hover {
    background: var(--bh-red);
    color: #FFFFFF;
}

.history-table {
    width: 100%;
    border-collapse: collapse;
    border: var(--bh-border-width) solid var(--bh-border);
    background: var(--bh-surface);
    font-size: 12px;
}

.history-table th {
    background: var(--bh-surface-alt);
    border-bottom: var(--bh-border-width) solid var(--bh-border);
    padding: 9px 12px;
    text-align: left;
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--bh-ink-secondary);
}

.history-table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--bh-border-subtle);
    color: var(--bh-ink);
}

.history-table tr:last-child td {
    border-bottom: none;
}

.dir-badge {
    display: inline-block;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.dir-badge.send {
    background: var(--bh-blue-subtle);
    border: 1px solid var(--bh-blue);
    color: var(--bh-blue);
}
.dir-badge.receive {
    background: var(--bh-green-subtle);
    border: 1px solid var(--bh-green);
    color: var(--bh-green);
}

/* Bottom App Footer */
.app-footer {
    padding: 10px 20px;
    border-top: var(--bh-border-width) solid var(--bh-border);
    background: var(--bh-surface-alt);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    font-weight: 600;
    color: var(--bh-ink-muted);
    letter-spacing: 0.04em;
}
</style>
</head>
<body>

<div class="app-frame">
    <!-- Top Bar -->
    <div class="top-bar">
        <div class="brand-unit">
            <a href="https://github.com/AniruthKarthik/qrtunnel" target="_blank" rel="noopener noreferrer" class="brand-emblem-box" title="QRTunnel on GitHub (AniruthKarthik/qrtunnel)">
                """ + ICONS['brand_emblem'] + """
            </a>
            <span class="brand-name">QRTunnel</span>
            <span class="version-tag mono">v""" + __version__ + """</span>
        </div>
        <div class="system-status mono">
            <span class="status-pip"></span>
            <span>READY // """ + (f"LAN: {current_lan_ip}:{port_val}" if has_lan else f"PORT {port_val}") + """</span>
        </div>
    </div>

    <!-- Segmented Tab Bar -->
    <div class="nav-row">
        <a href="/sender" class="nav-tab active" id="tab-btn-send" onclick="switchMainTab('send'); return false;">
            """ + ICONS['send'] + """
            <span>Send Files</span>
        </a>
        <a href="/receive" class="nav-tab" id="tab-btn-receive" onclick="switchMainTab('receive'); return false;">
            """ + ICONS['receive'] + """
            <span>Receive Files</span>
        </a>
        <button type="button" class="nav-tab" id="tab-btn-history" onclick="switchMainTab('history');">
            """ + ICONS['history'] + """
            <span>History</span>
        </button>
    </div>

    <!-- ==================== VIEW 1: SEND ==================== -->
    <div id="panel-send" class="main-view-panel active">
        <div class="workspace-grid">
            <!-- Left Pane: Controls & Manifest -->
            <div class="pane-primary">
                <div class="pane-header">
                    <div class="micro-label" style="margin-bottom: 4px;">Host Transfer // Outgoing</div>
                    <h1 id="page-title">Send Files</h1>
                    <p class="subtitle" id="page-subtitle">Select files to share via QR code or link</p>
                </div>

                <!-- SELECTION VIEW -->
                <div id="selection-view">
                    <div class="dropzone file-drop-area" id="drop-area">
                        <input type="file" id="file-input" multiple>
                        <div class="dropzone-icon">
                            """ + ICONS['file'] + """
                        </div>
                        <p class="dropzone-title" id="drop-text">Click or drag files here</p>
                        <p class="dropzone-hint">Select one or multiple files to send</p>
                    </div>

                    <div id="file-preview-area" class="manifest-box" style="display:none;">
                        <div class="manifest-topbar">
                            <div style="display:flex;align-items:center;gap:6px;">
                                <span class="micro-label">Staged Files</span>
                                <span class="file-count-chip mono" id="file-count-badge">0</span>
                            </div>
                            <button type="button" class="clear-btn" id="clear-btn">Clear All</button>
                        </div>
                        <ul class="manifest-list" id="file-list-preview"></ul>
                        <div class="manifest-footer mono" id="file-summary">0 files</div>
                    </div>

                    <div class="control-section">
                        <div class="control-header-row">
                            <span class="micro-label">Tunnel Mode</span>
                            <div class="port-input-wrap">
                                <span class="port-label">Port:</span>
                                <input type="number" id="port-input" min="1" max="65535" value="__PORT_VAL__" class="port-field mono" />
                                <button type="button" id="apply-port-btn" class="port-btn">Set</button>
                            </div>
                        </div>

                        <div class="mode-grid">
                            <label class="mode-tile selected" id="lbl-lan">
                                <input type="radio" name="mode" value="LAN" checked>
                                <span class="mode-tile-title">LAN</span>
                                <span class="mode-tile-sub">Wi-Fi</span>
                            </label>
                            <label class="mode-tile" id="lbl-cf">
                                <input type="radio" name="mode" value="Cloudflare">
                                <span class="mode-tile-title">Cloudflare</span>
                                <span class="mode-tile-sub">Tunnel</span>
                            </label>
                            <label class="mode-tile" id="lbl-ssh">
                                <input type="radio" name="mode" value="SSH">
                                <span class="mode-tile-title">SSH</span>
                                <span class="mode-tile-sub">Port 22/443</span>
                            </label>
                            <label class="mode-tile" id="lbl-ngrok">
                                <input type="radio" name="mode" value="Ngrok">
                                <span class="mode-tile-title">Ngrok</span>
                                <span class="mode-tile-sub">Secure</span>
                            </label>
                        </div>

                        <div id="lan-mode-notice" class="notice-box" style="display:none;">Not in same LAN, switching to the other connection...</div>
                        <div id="port-feedback" class="mono" style="display:none;font-size:11.5px;padding:6px 10px;margin-bottom:8px;border:1px solid #111215;"></div>

                        <button type="button" id="submit-btn" class="cta-button">Share Files</button>
                    </div>
                </div>

                <!-- ACTIVE VIEW FILE MANIFEST -->
                <div id="active-files-view" style="display:none;">
                    <div class="manifest-box" id="active-files-area">
                        <div class="manifest-topbar">
                            <span class="micro-label">Files Being Shared</span>
                            <span class="file-count-chip mono" id="active-file-count-badge">0</span>
                        </div>
                        <ul class="manifest-list" id="active-file-list"></ul>
                    </div>
                    <div id="lan-switch-notice" class="notice-box" style="display:none;margin-top:10px;">
                        Not in same LAN, switching to the other connection...
                    </div>
                </div>
            </div>

            <!-- Right Pane: QR Monolith & Telemetry Stage -->
            <div class="pane-stage">
                <!-- QR Monolith Card -->
                <div class="stage-card">
                    <div class="qr-monolith">
                        <div class="qr-wrapper" id="qr-wrapper"></div>
                    </div>
                    <p class="scan-prompt">Scan with phone camera to download files</p>

                    <!-- 4-Box Access Code Card -->
                    <div class="access-code-block">
                        <div class="access-code-header">
                            <div class="access-code-title">
                                """ + ICONS['lock'] + """
                                <span>ACCESS CODE</span>
                            </div>
                            <span class="access-code-sub">Enter on receiver</span>
                        </div>
                        <div class="digit-boxes" id="pin-badge-wrap">
                            <div class="digit-box mono" id="send-d-0">-</div>
                            <div class="digit-box mono" id="send-d-1">-</div>
                            <div class="digit-box mono" id="send-d-2">-</div>
                            <div class="digit-box mono" id="send-d-3">-</div>
                            <span id="pin-val" class="pin-hidden">----</span>
                        </div>
                    </div>

                    <!-- URL Row -->
                    <div class="url-strip">
                        """ + ICONS['link'] + """
                        <span class="url-text mono" id="target-url-text">http://...</span>
                        <button type="button" class="copy-btn" id="copy-btn">Copy Link</button>
                    </div>
                </div>

                <!-- Telemetry Dashboard -->
                <div id="progress-container" class="telemetry-card" style="display:none;">
                    <div class="telemetry-status-row">
                        <span id="progress-status-text" class="micro-label">Waiting for recipient to connect...</span>
                        <span class="spinner" id="progress-spinner"></span>
                    </div>
                    <div class="progress-track">
                        <div id="progress-bar" class="progress-bar-fill"></div>
                    </div>
                    <div class="telemetry-grid mono">
                        <div class="tele-cell">
                            <span class="tele-label">Transferred</span>
                            <span class="tele-val" id="progress-stats">0 B / 0 B</span>
                        </div>
                        <div class="tele-cell">
                            <span class="tele-label">Progress</span>
                            <span class="tele-val" id="progress-pct">0%</span>
                        </div>
                        <div class="tele-cell">
                            <span class="tele-label">Speed</span>
                            <span class="tele-val" id="progress-speed">0 B/s</span>
                        </div>
                        <div class="tele-cell">
                            <span class="tele-label">Remaining</span>
                            <span class="tele-val" id="progress-eta">--:--</span>
                        </div>
                    </div>
                </div>

                <div id="active-actions" style="display:none;">
                    <button type="button" id="stop-btn" class="stop-button">Stop Transfer & Close</button>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== VIEW 2: RECEIVE ==================== -->
    <div id="panel-receive" class="main-view-panel">
        <div class="workspace-grid">
            <!-- Left Pane: Controls & Incoming Manifest -->
            <div class="pane-primary">
                <div class="pane-header">
                    <div class="micro-label" style="margin-bottom: 4px;">Host Transfer // Ingest</div>
                    <h1>Receive Files</h1>
                    <p class="subtitle">Select connection mode to show QR code for upload</p>
                </div>

                <div class="control-section" style="margin-top:0;padding-top:0;">
                    <div class="control-header-row">
                        <span class="micro-label">Connection Mode</span>
                        <div class="port-input-wrap">
                            <span class="port-label">Port:</span>
                            <input type="number" id="rec-port-input" min="1" max="65535" value="__PORT_VAL__" class="port-field mono" />
                            <button type="button" id="port-apply-btn" class="port-btn">Set</button>
                        </div>
                    </div>

                    <div class="mode-grid">
                        <button type="button" class="mode-tile active" data-mode="LAN">
                            <span class="mode-tile-title">LAN</span>
                            <span class="mode-tile-sub">Wi-Fi</span>
                        </button>
                        <button type="button" class="mode-tile" data-mode="Cloudflare">
                            <span class="mode-tile-title">Cloudflare</span>
                            <span class="mode-tile-sub">Tunnel</span>
                        </button>
                        <button type="button" class="mode-tile" data-mode="SSH">
                            <span class="mode-tile-title">SSH</span>
                            <span class="mode-tile-sub">Port 22/443</span>
                        </button>
                        <button type="button" class="mode-tile" data-mode="Ngrok">
                            <span class="mode-tile-title">Ngrok</span>
                            <span class="mode-tile-sub">Secure</span>
                        </button>
                    </div>
                    <div id="rec-notice-box" class="notice-box" style="display:none;"></div>
                </div>

                <!-- Incoming Transfers Box -->
                <div class="incoming-card">
                    <div class="incoming-topbar">
                        <span class="micro-label">Incoming Transfers</span>
                        <span class="file-count-chip mono" title="Save directory">📁 """ + cwd_name + """</span>
                    </div>

                    <!-- In-flight Upload Progress Card -->
                    <div id="rec-progress-card" class="telemetry-card" style="display:none;border:none;border-bottom:1px solid var(--bh-border);">
                        <div class="telemetry-status-row">
                            <span id="rec-progress-label" class="micro-label">Uploading...</span>
                            <span id="rec-progress-pct" class="mono" style="font-weight:700;color:var(--bh-blue);">0%</span>
                        </div>
                        <div class="progress-track" style="margin-bottom:0;">
                            <div id="rec-progress-bar-fill" class="progress-bar-fill"></div>
                        </div>
                    </div>

                    <ul class="manifest-list" id="received-list"></ul>
                    <div id="empty-state" class="empty-state">
                        """ + ICONS['upload_cloud'] + """
                        <span>No files received yet. Waiting for uploads...</span>
                    </div>
                </div>

                <button type="button" id="close-session-btn" class="stop-button" style="margin-top:auto;">Close Session</button>
            </div>

            <!-- Right Pane: Stage Monolith -->
            <div class="pane-stage">
                <div class="stage-card">
                    <div id="rec-loading-spinner" class="loading-overlay" style="display:none;">
                        <div class="spinner"></div>
                        <span id="rec-loading-text" class="micro-label">Connecting...</span>
                    </div>
                    <div class="qr-monolith">
                        <div class="qr-wrapper" id="rec-qr-wrapper">""" + rec_init_qr_svg + """</div>
                    </div>
                    <p class="scan-prompt">Scan with phone camera to open upload page</p>

                    <!-- 4-Box Access Code Card -->
                    <div class="access-code-block">
                        <div class="access-code-header">
                            <div class="access-code-title">
                                """ + ICONS['lock'] + """
                                <span>ACCESS CODE</span>
                            </div>
                            <span class="access-code-sub">Enter on phone</span>
                        </div>
                        <div class="digit-boxes">
                            <div class="digit-box mono" id="rec-d-0">""" + pin_d0 + """</div>
                            <div class="digit-box mono" id="rec-d-1">""" + pin_d1 + """</div>
                            <div class="digit-box mono" id="rec-d-2">""" + pin_d2 + """</div>
                            <div class="digit-box mono" id="rec-d-3">""" + pin_d3 + """</div>
                            <span id="pin-display" class="pin-hidden">""" + pin_str + """</span>
                        </div>
                    </div>

                    <!-- URL Row -->
                    <div class="url-strip">
                        """ + ICONS['link'] + """
                        <span class="url-text mono" id="rec-target-url-text">""" + rec_init_url + """</span>
                        <button type="button" class="copy-btn" id="rec-copy-btn">Copy Link</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- ==================== VIEW 3: HISTORY ==================== -->
    <div id="panel-history" class="main-view-panel">
        <div class="history-container">
            <div class="history-top">
                <div>
                    <div class="micro-label" style="margin-bottom: 4px;">Transfer Manifest // Audit Log</div>
                    <h1 style="font-size: 20px; font-weight: 800; text-transform: uppercase;">Transfer History</h1>
                </div>
                <div class="history-filters">
                    <button type="button" class="filter-btn active" data-filter="all" onclick="filterHistory('all')">All</button>
                    <button type="button" class="filter-btn" data-filter="send" onclick="filterHistory('send')">Sent</button>
                    <button type="button" class="filter-btn" data-filter="receive" onclick="filterHistory('receive')">Received</button>
                    <button type="button" class="clear-history-btn" onclick="clearHistoryLogs()">Clear</button>
                </div>
            </div>

            <table class="history-table">
                <thead>
                    <tr>
                        <th>Time (UTC)</th>
                        <th>Direction</th>
                        <th>Filename</th>
                        <th>Size</th>
                        <th>Remote Host</th>
                    </tr>
                </thead>
                <tbody id="history-tbody">
                    <tr><td colspan="5" style="text-align:center;padding:24px;color:var(--bh-ink-muted);">Loading transfer history...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
let activeTab = "send";
function switchMainTab(tab) {
    if (tab !== 'send' && tab !== 'receive' && tab !== 'history') {
        tab = 'send';
    }
    activeTab = tab;
    const isSend = tab === 'send';
    const isRec = tab === 'receive';
    const isHist = tab === 'history';

    document.getElementById('tab-btn-send').classList.toggle('active', isSend);
    document.getElementById('tab-btn-receive').classList.toggle('active', isRec);
    document.getElementById('tab-btn-history').classList.toggle('active', isHist);

    document.getElementById('panel-send').classList.toggle('active', isSend);
    document.getElementById('panel-receive').classList.toggle('active', isRec);
    document.getElementById('panel-history').classList.toggle('active', isHist);

    window.location.hash = '#' + tab;

    if (isRec) {
        if (!currentRecState || currentRecState.is_send !== false) {
            switchRecMode(currentRecMode, currentRecPort);
        }
    } else if (isHist) {
        loadHistoryData();
    }
}

function setPinDigits(pinStr, prefix) {
    const s = String(pinStr || '----').padEnd(4, '-');
    for (let i = 0; i < 4; i++) {
        const el = document.getElementById(prefix + '-d-' + i);
        if (el) el.textContent = s[i] || '-';
    }
}

let selectedFiles = [];
const fileInput = document.getElementById('file-input');
const dropArea = document.getElementById('drop-area');
const dropText = document.getElementById('drop-text');
const previewArea = document.getElementById('file-preview-area');
const listPreview = document.getElementById('file-list-preview');
const fileSummary = document.getElementById('file-summary');
const fileCountBadge = document.getElementById('file-count-badge');
const submitBtn = document.getElementById('submit-btn');
const clearBtn = document.getElementById('clear-btn');

const selectionView = document.getElementById('selection-view');
const activeFilesView = document.getElementById('active-files-view');
const qrWrapper = document.getElementById('qr-wrapper');
const pinVal = document.getElementById('pin-val');
const targetUrlText = document.getElementById('target-url-text');
const copyBtn = document.getElementById('copy-btn');
const activeFileCountBadge = document.getElementById('active-file-count-badge');
const activeFileList = document.getElementById('active-file-list');
const activeActions = document.getElementById('active-actions');

const progressContainer = document.getElementById('progress-container');
const progressSpinner = document.getElementById('progress-spinner');
const progressStatusText = document.getElementById('progress-status-text');
const progressBar = document.getElementById('progress-bar');
const progressPct = document.getElementById('progress-pct');
const progressSpeed = document.getElementById('progress-speed');
const progressStats = document.getElementById('progress-stats');
const progressEta = document.getElementById('progress-eta');
const stopBtn = document.getElementById('stop-btn');

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    var kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    var mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + ' MB';
    var gb = mb / 1024;
    return gb.toFixed(1) + ' GB';
}

function formatDuration(sec) {
    if (!sec || !isFinite(sec) || sec <= 0) return '--:--';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
}

function updateFileList() {
    listPreview.innerHTML = '';
    if (selectedFiles.length > 0) {
        let total = 0;
        selectedFiles.forEach((file, idx) => {
            total += file.size;
            const li = document.createElement('li');
            li.innerHTML = `
              <div class="manifest-item-left">
                """ + ICONS['file'] + """
                <span class="manifest-name mono" title="${file.name}">${file.name}</span>
              </div>
              <div class="manifest-meta">
                <span class="manifest-size mono">${formatBytes(file.size)}</span>
                <button type="button" class="remove-btn" data-idx="${idx}" title="Remove file">✕</button>
              </div>`;
            listPreview.appendChild(li);
        });
        fileCountBadge.textContent = selectedFiles.length;
        fileSummary.textContent = `${selectedFiles.length} ${selectedFiles.length === 1 ? 'FILE' : 'FILES'} (${formatBytes(total)})`;
        submitBtn.textContent = `SHARE ${selectedFiles.length} ${selectedFiles.length === 1 ? 'FILE' : 'FILES'}`;
        submitBtn.classList.add('enabled');
        previewArea.style.display = 'block';
        dropText.textContent = 'ADD MORE FILES';
    } else {
        fileCountBadge.textContent = '0';
        previewArea.style.display = 'none';
        submitBtn.textContent = 'SHARE FILES';
        submitBtn.classList.remove('enabled');
        dropText.textContent = 'CLICK OR DRAG FILES HERE';
    }
}

fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
        for (let i = 0; i < fileInput.files.length; i++) {
            const f = fileInput.files[i];
            if (!selectedFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
                selectedFiles.push(f);
            }
        }
        fileInput.value = '';
        updateFileList();
    }
});

listPreview.addEventListener('click', (e) => {
    if (e.target.classList.contains('remove-btn')) {
        const idx = parseInt(e.target.getAttribute('data-idx'), 10);
        selectedFiles.splice(idx, 1);
        updateFileList();
    }
});

clearBtn.addEventListener('click', () => {
    selectedFiles = [];
    updateFileList();
});

['dragenter', 'dragover'].forEach(n => dropArea.addEventListener(n, (e) => {
    e.preventDefault();
    dropArea.classList.add('dragover');
}));
['dragleave', 'drop'].forEach(n => dropArea.addEventListener(n, (e) => {
    e.preventDefault();
    dropArea.classList.remove('dragover');
}));
dropArea.addEventListener('drop', (e) => {
    if (e.dataTransfer.files.length) {
        for (let i = 0; i < e.dataTransfer.files.length; i++) {
            const f = e.dataTransfer.files[i];
            if (!selectedFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
                selectedFiles.push(f);
            }
        }
        updateFileList();
    }
});

const portInput = document.getElementById('port-input');
const applyPortBtn = document.getElementById('apply-port-btn');
const portFeedback = document.getElementById('port-feedback');
const lanSwitchNotice = document.getElementById('lan-switch-notice');
const lanModeNotice = document.getElementById('lan-mode-notice');

if (applyPortBtn && portInput) {
    applyPortBtn.addEventListener('click', () => {
        const newPort = parseInt(portInput.value, 10);
        if (!newPort || newPort < 1 || newPort > 65535) {
            portFeedback.style.display = 'block';
            portFeedback.style.background = 'var(--bh-red-subtle)';
            portFeedback.style.color = 'var(--bh-red)';
            portFeedback.textContent = 'Please enter a valid port number (1–65535).';
            return;
        }
        applyPortBtn.textContent = '...';
        applyPortBtn.style.pointerEvents = 'none';

        fetch('/api/sender/port', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ port: newPort })
        })
        .then(r => r.json())
        .then(data => {
            applyPortBtn.textContent = 'SET';
            applyPortBtn.style.pointerEvents = 'auto';
            if (data.success) {
                portFeedback.style.display = 'block';
                portFeedback.style.background = 'var(--bh-green-subtle)';
                portFeedback.style.color = 'var(--bh-green)';
                portFeedback.textContent = `✓ Port set to ${data.port}`;
                if (recPortInput) recPortInput.value = data.port;
                if (portInput) portInput.value = data.port;
                currentRecPort = data.port;
                if (typeof initialState !== 'undefined' && initialState) initialState.port = data.port;
                setTimeout(() => { portFeedback.style.display = 'none'; }, 3500);
            } else {
                portFeedback.style.display = 'block';
                portFeedback.style.background = 'var(--bh-red-subtle)';
                portFeedback.style.color = 'var(--bh-red)';
                portFeedback.textContent = data.error || 'Failed to update port.';
            }
        })
        .catch(() => {
            applyPortBtn.textContent = 'SET';
            applyPortBtn.style.pointerEvents = 'auto';
            portFeedback.style.display = 'block';
            portFeedback.style.background = 'var(--bh-red-subtle)';
            portFeedback.style.color = 'var(--bh-red)';
            portFeedback.textContent = 'Error contacting server to update port.';
        });
    });

    portInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            applyPortBtn.click();
        }
    });
}

document.querySelectorAll('input[name="mode"]').forEach(radio => {
    radio.addEventListener('change', () => {
        document.querySelectorAll('.mode-tile').forEach(l => {
            if (l.tagName.toLowerCase() === 'label') l.classList.remove('selected');
        });
        radio.closest('label').classList.add('selected');
        if (radio.value === 'LAN') {
            const hasLan = initialState.lan_ip && initialState.lan_ip !== '127.0.0.1' && initialState.lan_ip !== 'localhost' && initialState.lan_ip !== 'None';
            if (!hasLan) {
                if (lanModeNotice) {
                    lanModeNotice.style.display = 'block';
                    lanModeNotice.textContent = 'Not in same LAN, switching to the other connection...';
                }
                setTimeout(() => {
                    const cfRadio = document.querySelector('input[name="mode"][value="Cloudflare"]');
                    if (cfRadio) {
                        cfRadio.checked = true;
                        document.querySelectorAll('.mode-tile').forEach(l => {
                            if (l.tagName.toLowerCase() === 'label') l.classList.remove('selected');
                        });
                        const lblCf = document.getElementById('lbl-cf');
                        if (lblCf) lblCf.classList.add('selected');
                    }
                }, 800);
            } else if (lanModeNotice) {
                lanModeNotice.style.display = 'none';
            }
        } else if (lanModeNotice) {
            lanModeNotice.style.display = 'none';
        }
    });
});

submitBtn.addEventListener('click', () => {
    if (!selectedFiles.length) return;
    submitBtn.classList.remove('enabled');
    submitBtn.textContent = 'PREPARING DISPATCH...';

    const selectedMode = document.querySelector('input[name="mode"]:checked').value;
    const chosenPort = (portInput && parseInt(portInput.value, 10)) || (initialState && initialState.port) || 6969;
    const formData = new FormData();
    selectedFiles.forEach(f => formData.append('file', f));

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/sender/share?mode=${encodeURIComponent(selectedMode)}&port=${chosenPort}`, true);

    xhr.onload = () => {
        if (xhr.status === 200) {
            try {
                const res = JSON.parse(xhr.responseText);
                switchToActiveView(res);
            } catch (err) {
                alert('Transfer started');
            }
        } else {
            alert('Failed to start sharing: ' + xhr.statusText);
            submitBtn.classList.add('enabled');
            submitBtn.textContent = 'SHARE FILES';
        }
    };
    xhr.onerror = () => {
        alert('Network error while starting transfer');
        submitBtn.classList.add('enabled');
        submitBtn.textContent = 'SHARE FILES';
    };
    xhr.send(formData);
});

function switchToActiveView(data) {
    selectionView.style.display = 'none';
    activeFilesView.style.display = 'block';
    activeActions.style.display = 'block';
    progressContainer.style.display = 'block';

    document.getElementById('page-title').textContent = data.is_send !== false ? 'SHARING FILES' : 'RECEIVING FILES';
    document.getElementById('page-subtitle').textContent = data.is_send !== false ? 'Scan QR code with phone camera to download' : 'Scan to send files';

    if (data.qr_svg) {
        qrWrapper.innerHTML = data.qr_svg;
    }
    pinVal.textContent = data.pin || '----';
    setPinDigits(data.pin, 'send');
    targetUrlText.textContent = data.target_url || '';

    if (data.notice && lanSwitchNotice) {
        lanSwitchNotice.textContent = data.notice;
        lanSwitchNotice.style.display = 'block';
    } else if (lanSwitchNotice) {
        lanSwitchNotice.style.display = 'none';
    }

    activeFileList.innerHTML = '';
    const files = data.files || [];
    activeFileCountBadge.textContent = files.length;
    files.forEach(f => {
        const li = document.createElement('li');
        li.innerHTML = `
          <div class="manifest-item-left">
            """ + ICONS['file'] + """
            <span class="manifest-name mono" title="${f.name}">${f.name}</span>
          </div>
          <div class="manifest-meta">
            <span class="manifest-size mono">${formatBytes(f.size)}</span>
          </div>`;
        activeFileList.appendChild(li);
    });

    progressStatusText.textContent = 'Waiting for recipient to connect...';
}

copyBtn.addEventListener('click', () => {
    const url = targetUrlText.textContent;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(() => {
            copyBtn.textContent = 'COPIED!';
            setTimeout(() => copyBtn.textContent = 'COPY LINK', 1500);
        });
    }
});

/* ── RECEIVER VIEW LOGIC ── */
let currentRecMode = "LAN";
let currentRecPort = (typeof __INITIAL_STATE__ !== 'undefined' && __INITIAL_STATE__ && __INITIAL_STATE__.port) || 6969;
let currentRecUrl = "";
let currentRecState = null;

const recQrWrapper = document.getElementById('rec-qr-wrapper');
const pinDisplay = document.getElementById('pin-display');
const recTargetUrlText = document.getElementById('rec-target-url-text');
const recCopyBtn = document.getElementById('rec-copy-btn');
const recPortInput = document.getElementById('rec-port-input');
const portApplyBtn = document.getElementById('port-apply-btn');
const recNoticeBox = document.getElementById('rec-notice-box');
const recLoadingSpinner = document.getElementById('rec-loading-spinner');
const recLoadingText = document.getElementById('rec-loading-text');
const receivedList = document.getElementById('received-list');
const emptyState = document.getElementById('empty-state');
const recProgressCard = document.getElementById('rec-progress-card');
const recProgressBarFill = document.getElementById('rec-progress-bar-fill');
const recProgressPct = document.getElementById('rec-progress-pct');
const recProgressLabel = document.getElementById('rec-progress-label');
const closeSessionBtn = document.getElementById('close-session-btn');

function updateRecUi(data) {
    if (!data) return;
    currentRecState = data;
    if (data.mode_name) {
        currentRecMode = data.mode_name;
        document.querySelectorAll('.mode-tile').forEach(btn => {
            if (btn.hasAttribute('data-mode')) {
                btn.classList.toggle('active', btn.getAttribute('data-mode') === data.mode_name);
            }
        });
    }
    if (data.port) {
        currentRecPort = data.port;
        if (recPortInput) recPortInput.value = data.port;
        if (portInput) portInput.value = data.port;
    }
    if (data.pin) {
        pinDisplay.textContent = data.pin;
        setPinDigits(data.pin, 'rec');
    }
    if (data.target_url) {
        currentRecUrl = data.target_url;
        recTargetUrlText.textContent = data.target_url;
    }
    if (data.qr_svg) {
        recQrWrapper.innerHTML = data.qr_svg;
    }
    if (data.notice) {
        recNoticeBox.textContent = data.notice;
        recNoticeBox.style.display = 'block';
    } else {
        recNoticeBox.style.display = 'none';
    }
    if (data.received_files && Array.isArray(data.received_files)) {
        renderReceivedFiles(data.received_files);
    }
}

function renderReceivedFiles(files) {
    receivedList.innerHTML = '';
    if (files.length === 0) {
        emptyState.style.display = 'flex';
    } else {
        emptyState.style.display = 'none';
        files.forEach(f => {
            const li = document.createElement('li');
            li.innerHTML = `
              <div class="manifest-item-left">
                """ + ICONS['check'] + """
                <span class="manifest-name mono" title="${f.name}">${f.name}</span>
              </div>
              <div class="manifest-meta">
                <span class="manifest-size mono">${formatBytes(f.size)}</span>
              </div>`;
            receivedList.appendChild(li);
        });
    }
}

function addReceivedFile(f) {
    emptyState.style.display = 'none';
    const li = document.createElement('li');
    li.innerHTML = `
      <div class="manifest-item-left">
        """ + ICONS['check'] + """
        <span class="manifest-name mono" title="${f.name}">${f.name}</span>
      </div>
      <div class="manifest-meta">
        <span class="manifest-size mono">${formatBytes(f.size)}</span>
      </div>`;
    receivedList.prepend(li);
}

function switchRecMode(newMode, portVal) {
    recLoadingText.textContent = `CONNECTING ${newMode}...`;
    recLoadingSpinner.style.display = 'flex';
    const port = portVal || currentRecPort;

    fetch(`/api/receiver/mode?mode=${encodeURIComponent(newMode)}&port=${port}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                updateRecUi(data);
            } else {
                alert('Could not switch mode: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(() => {
            alert('Network error switching connection mode');
        })
        .finally(() => {
            recLoadingSpinner.style.display = 'none';
        });
}

document.querySelectorAll('.mode-tile').forEach(btn => {
    if (btn.hasAttribute('data-mode')) {
        btn.addEventListener('click', () => {
            const mode = btn.getAttribute('data-mode');
            switchRecMode(mode, currentRecPort);
        });
    }
});

if (portApplyBtn && recPortInput) {
    portApplyBtn.addEventListener('click', () => {
        const val = parseInt(recPortInput.value, 10);
        if (!val || val < 1 || val > 65535) {
            alert('Please enter a valid port between 1 and 65535');
            return;
        }
        switchRecMode(currentRecMode, val);
    });
    recPortInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            portApplyBtn.click();
        }
    });
}

recCopyBtn.addEventListener('click', () => {
    if (!currentRecUrl) return;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(currentRecUrl).then(() => {
            recCopyBtn.textContent = 'COPIED!';
            setTimeout(() => { recCopyBtn.textContent = 'COPY LINK'; }, 1500);
        });
    }
});

function showSessionEnded() {
    document.body.innerHTML = `
      <div class="app-frame" style="max-width:480px;margin:40px auto;text-align:center;padding:48px 32px;">
        <div class="brand-emblem-box" style="margin:0 auto 16px;">
          """ + ICONS['stop'] + """
        </div>
        <div class="micro-label" style="margin-bottom:6px;">SESSION COMPLETED</div>
        <h1 style="font-size:22px;font-weight:800;color:var(--bh-ink);margin-bottom:8px;">Session Ended</h1>
        <p class="subtitle" style="margin-bottom:24px;">qrtunnel has stopped. You can safely close this window.</p>
        <div class="app-footer mono" style="justify-content:center;">QRTUNNEL TERMINATED</div>
      </div>`;
}

stopBtn.addEventListener('click', () => {
    fetch('/api/sender/stop', { method: 'POST' }).finally(() => {
        showSessionEnded();
    });
});

closeSessionBtn.addEventListener('click', () => {
    fetch('/api/sender/close', { method: 'POST' }).finally(() => {
        showSessionEnded();
    });
});

function closeNotification() {
    navigator.sendBeacon('/api/sender/close');
}
window.addEventListener('beforeunload', closeNotification);
window.addEventListener('pagehide', closeNotification);

setInterval(() => {
    fetch('/api/sender/heartbeat', { method: 'POST', keepalive: true }).catch(() => {});
}, 1500);

/* History Loader */
let currentHistoryData = [];
function loadHistoryData() {
    const tbody = document.getElementById('history-tbody');
    fetch('/api/history')
        .then(r => r.json())
        .then(d => {
            currentHistoryData = d.history || [];
            renderHistoryRows(currentHistoryData);
        })
        .catch(() => {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--bh-red);">Failed to retrieve history logs.</td></tr>';
        });
}

function renderHistoryRows(entries) {
    const tbody = document.getElementById('history-tbody');
    tbody.innerHTML = '';
    if (!entries.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:28px;color:var(--bh-ink-muted);">No recorded transfers found.</td></tr>';
        return;
    }
    entries.slice().reverse().forEach(item => {
        const tr = document.createElement('tr');
        const isSend = (item.direction || '').toLowerCase() === 'send';
        const dirBadge = isSend ? '<span class="dir-badge send">SENT</span>' : '<span class="dir-badge receive">RECEIVED</span>';
        const ts = item.timestamp ? item.timestamp.replace('T', ' ').substring(0, 19) : '-';
        tr.innerHTML = `
            <td class="mono" style="color:var(--bh-ink-muted);font-size:11px;">${ts}</td>
            <td>${dirBadge}</td>
            <td class="mono" style="font-weight:600;">${item.filename || '-'}</td>
            <td class="mono">${formatBytes(item.size || 0)}</td>
            <td class="mono" style="color:var(--bh-ink-secondary);">${item.client_ip || '-'}</td>
        `;
        tbody.appendChild(tr);
    });
}

function filterHistory(filter) {
    document.querySelectorAll('.filter-btn').forEach(b => {
        b.classList.toggle('active', b.getAttribute('data-filter') === filter);
    });
    if (filter === 'all') {
        renderHistoryRows(currentHistoryData);
    } else {
        const filtered = currentHistoryData.filter(i => (i.direction || '').toLowerCase() === filter);
        renderHistoryRows(filtered);
    }
}

function clearHistoryLogs() {
    if (!confirm('Clear all transfer history logs?')) return;
    fetch('/api/history/clear', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                currentHistoryData = [];
                renderHistoryRows([]);
            }
        })
        .catch(() => {
            alert('Failed to clear history logs.');
        });
}

// Initialize with current server state
const initialState = __INITIAL_STATE__;
const initialPort = (initialState && initialState.port) || "__PORT_VAL__";
if (portInput && !portInput.value) portInput.value = initialPort;
if (recPortInput && !recPortInput.value) recPortInput.value = initialPort;

if (initialState) {
    if (initialState.is_active && initialState.is_send !== false) {
        switchToActiveView(initialState);
    }
    if (initialState.is_send === false) {
        updateRecUi(initialState);
    } else if (initialState.rec_initial) {
        updateRecUi(initialState.rec_initial);
    }
}

const requestedTab = "__DEFAULT_TAB__";
const hash = window.location.hash.toLowerCase();
if (hash === '#receive' || requestedTab === 'receive') {
    switchMainTab('receive');
} else if (hash === '#history') {
    switchMainTab('history');
} else {
    switchMainTab('send');
}

const evtSource = new EventSource('/api/sender/events');

evtSource.addEventListener('state', (e) => {
    try {
        const state = JSON.parse(e.data);
        if (state.is_send !== false && state.is_active) {
            switchToActiveView(state);
        } else if (state.is_send === false) {
            updateRecUi(state);
        }
    } catch (err) {}
});

evtSource.addEventListener('progress', (e) => {
    try {
        const data = JSON.parse(e.data);
        const pct = data.pct || 0;
        const speed = data.speed || 0;
        const total = data.total || 0;
        const trans = data.transferred || 0;

        progressBar.style.width = pct + '%';
        progressPct.textContent = pct + '%';
        progressSpeed.textContent = formatBytes(speed) + '/s';
        progressStats.textContent = `${formatBytes(trans)} / ${formatBytes(total)}`;

        if (speed > 0 && total > trans) {
            const remSec = (total - trans) / speed;
            progressEta.textContent = formatDuration(remSec);
        } else if (pct >= 100) {
            progressEta.textContent = '00:00';
        } else {
            progressEta.textContent = '--:--';
        }

        if (data.status === 'completed') {
            progressSpinner.style.display = 'none';
            progressStatusText.textContent = '✓ Transfer Complete!';
            progressBar.style.background = 'var(--bh-green)';
        } else {
            progressSpinner.style.display = 'inline-block';
            progressStatusText.textContent = data.label ? `Transferring ${data.label}...` : 'Transferring...';
            progressBar.style.background = 'var(--bh-blue)';
        }

        // Update receive progress
        if (data.status === 'transferring') {
            recProgressCard.style.display = 'block';
            recProgressLabel.textContent = data.label || 'Uploading...';
            recProgressPct.textContent = pct + '%';
            recProgressBarFill.style.width = pct + '%';
        } else if (data.status === 'completed') {
            recProgressPct.textContent = '100%';
            recProgressBarFill.style.width = '100%';
            setTimeout(() => { recProgressCard.style.display = 'none'; }, 2000);
        }
    } catch (err) {}
});

evtSource.addEventListener('received', (e) => {
    try {
        const data = JSON.parse(e.data);
        addReceivedFile(data);
    } catch (err) {}
});

evtSource.addEventListener('close', () => {
    showSessionEnded();
});
</script>
</body>
</html>"""

    html = (
        html.replace("__INITIAL_STATE__", initial_state_json)
        .replace("__DEFAULT_TAB__", default_tab)
        .replace("__PORT_VAL__", str(port_val))
    )
    return html
