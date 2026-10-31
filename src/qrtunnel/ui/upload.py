"""Bauhaus Client Upload Page - Client sending files to host."""

from .session import render_receiver_session_script
from .theme import BAUHAUS_CSS, ICONS


def render_upload_page() -> str:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>QRTunnel — Send Files</title>
<style>
""" + BAUHAUS_CSS + """

body {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--bh-space-6) var(--bh-space-4);
}

.upload-frame {
    background: var(--bh-surface);
    border: var(--bh-border-heavy) solid var(--bh-border);
    padding: var(--bh-space-8) var(--bh-space-6);
    max-width: 480px;
    width: 100%;
}

@media (max-width: 520px) {
    .upload-frame {
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

.drop-zone {
    position: relative;
    border: 2px dashed var(--bh-border);
    background: var(--bh-surface-alt);
    padding: var(--bh-space-8) var(--bh-space-4);
    text-align: center;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease;
    margin-bottom: var(--bh-space-5);
}

.drop-zone:hover, .drop-zone.dragover {
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

.drop-icon-box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    background: var(--bh-surface);
    border: var(--bh-border-width) solid var(--bh-border);
    color: var(--bh-blue);
    margin-bottom: var(--bh-space-3);
}

.drop-text {
    font-size: 14px;
    font-weight: 700;
    color: var(--bh-ink);
    margin-bottom: 3px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.drop-hint {
    font-size: 12px;
    color: var(--bh-ink-muted);
}

.file-preview-area {
    margin-bottom: var(--bh-space-5);
    border: var(--bh-border-width) solid var(--bh-border);
    background: var(--bh-surface-alt);
}

.file-preview-header {
    padding: 8px 12px;
    background: var(--bh-surface);
    border-bottom: 1px solid var(--bh-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.file-summary {
    font-size: 12px;
    font-weight: 700;
    color: var(--bh-blue);
}

.file-list-preview {
    list-style: none;
    max-height: 170px;
    overflow-y: auto;
}

.file-list-preview li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 9px 12px;
    border-bottom: 1px solid var(--bh-border-subtle);
    font-size: 12px;
    color: var(--bh-ink);
}

.file-list-preview li:last-child {
    border-bottom: none;
}

.file-preview-name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 70%;
}

.file-preview-size {
    color: var(--bh-ink-muted);
    font-weight: 600;
    white-space: nowrap;
}

.progress-container {
    display: none;
    background: var(--bh-surface-alt);
    border: var(--bh-border-width) solid var(--bh-border);
    padding: var(--bh-space-4);
    margin-bottom: var(--bh-space-5);
}

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

.submit-button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
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
    transition: all 0.12s ease;
    opacity: 0.4;
    pointer-events: none;
}

.submit-button.enabled {
    opacity: 1;
    pointer-events: auto;
}

.submit-button.enabled:hover {
    background: var(--bh-blue-dark);
}

.submit-button.enabled:active {
    transform: translateY(1px);
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
<div class="upload-frame">
    <div class="header-block">
        <div class="brand-badge">
            """ + ICONS['upload_cloud'] + """
        </div>
        <div class="micro-label" style="margin-bottom: 6px;">Receiver Mode // Upload Portal</div>
        <h1>Send Files</h1>
        <p class="subtitle">Select files to send to this computer</p>
    </div>

    <form id="upload-form" action="/upload" method="post" enctype="multipart/form-data">
        <div class="drop-zone" id="drop-area">
            <input type="file" id="file-input" name="file" multiple required>
            <div class="drop-icon-box">
                """ + ICONS['file'] + """
            </div>
            <p class="drop-text" id="drop-text">Tap to select files</p>
            <p class="drop-hint">or drag and drop multiple files here</p>
        </div>

        <div id="file-preview-area" class="file-preview-area" style="display:none;">
            <div class="file-preview-header">
                <span class="micro-label">Staged Files</span>
                <div id="file-summary" class="file-summary mono"></div>
            </div>
            <ul id="file-list-preview" class="file-list-preview"></ul>
        </div>

        <div id="progress-container" class="progress-container">
            <div class="progress-bar-bg">
                <div id="progress-bar" class="progress-bar-fill"></div>
            </div>
            <div class="progress-info mono">
                <span id="progress-pct">0%</span>
                <span id="progress-speed">0 B/s</span>
                <span id="progress-stats">0 B / 0 B</span>
            </div>
        </div>

        <button type="submit" id="submit-btn" class="submit-button">Upload Files</button>
    </form>

    <div class="footer-meta mono">QRTUNNEL // MULTIPART FILE INGEST</div>
</div>

<script>
const fileInput = document.getElementById('file-input');
const dropText = document.getElementById('drop-text');
const filePreviewArea = document.getElementById('file-preview-area');
const fileSummary = document.getElementById('file-summary');
const fileListPreview = document.getElementById('file-list-preview');
const submitButton = document.getElementById('submit-btn');
const uploadForm = document.getElementById('upload-form');
const progressContainer = document.getElementById('progress-container');
const progressBar = document.getElementById('progress-bar');
const progressPct = document.getElementById('progress-pct');
const progressSpeed = document.getElementById('progress-speed');
const progressStats = document.getElementById('progress-stats');
const dropArea = document.getElementById('drop-area');

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    var kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    var mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + ' MB';
    var gb = mb / 1024;
    return gb.toFixed(1) + ' GB';
}

fileInput.addEventListener('change', () => {
    fileListPreview.innerHTML = '';
    if (fileInput.files.length > 0) {
        var totalBytes = 0;
        for (var i = 0; i < fileInput.files.length; i++) {
            totalBytes += fileInput.files[i].size;
            var li = document.createElement('li');
            var nameSpan = document.createElement('span');
            nameSpan.className = 'file-preview-name mono';
            nameSpan.textContent = fileInput.files[i].name;
            var sizeSpan = document.createElement('span');
            sizeSpan.className = 'file-preview-size mono';
            sizeSpan.textContent = formatBytes(fileInput.files[i].size);
            li.appendChild(nameSpan);
            li.appendChild(sizeSpan);
            fileListPreview.appendChild(li);
        }
        if (fileInput.files.length === 1) {
            fileSummary.textContent = '1 file (' + formatBytes(totalBytes) + ')';
            submitButton.textContent = 'Upload 1 File';
        } else {
            fileSummary.textContent = fileInput.files.length + ' files (' + formatBytes(totalBytes) + ')';
            submitButton.textContent = 'Upload ' + fileInput.files.length + ' Files';
        }
        filePreviewArea.style.display = 'block';
        dropText.textContent = fileInput.files.length === 1 ? 'Change selected file' : 'Change selected files';
        submitButton.classList.add('enabled');
    } else {
        filePreviewArea.style.display = 'none';
        dropText.textContent = 'Tap to select files';
        submitButton.textContent = 'Upload Files';
        submitButton.classList.remove('enabled');
    }
});

['dragenter', 'dragover'].forEach(n => dropArea.addEventListener(n, (e) => {
    e.preventDefault();
    dropArea.classList.add('dragover');
}));
['dragleave', 'drop'].forEach(n => dropArea.addEventListener(n, (e) => {
    e.preventDefault();
    dropArea.classList.remove('dragover');
}));

uploadForm.addEventListener('submit', (e) => {
    if (!fileInput.files.length) return;
    e.preventDefault();
    submitButton.classList.remove('enabled');
    submitButton.textContent = 'Uploading...';
    progressContainer.style.display = 'block';
    window._isUploading = true;

    const formData = new FormData(uploadForm);
    const xhr = new XMLHttpRequest();
    let startTime = Date.now();
    let lastLoaded = 0;

    xhr.open('POST', '/upload', true);

    xhr.upload.onprogress = (evt) => {
        if (evt.lengthComputable) {
            const pct = Math.round((evt.loaded / evt.total) * 100);
            progressBar.style.width = pct + '%';
            progressPct.textContent = pct + '%';
            progressStats.textContent = formatBytes(evt.loaded) + ' / ' + formatBytes(evt.total);
            const now = Date.now();
            const elapsed = (now - startTime) / 1000;
            if (elapsed > 0.2) {
                const speed = (evt.loaded - lastLoaded) / elapsed;
                progressSpeed.textContent = formatBytes(speed) + '/s';
                startTime = now;
                lastLoaded = evt.loaded;
            }
        }
    };

    xhr.onload = () => {
        window._isUploading = false;
        if (xhr.status === 200) {
            document.open();
            document.write(xhr.responseText);
            document.close();
        } else {
            alert('Upload failed: ' + xhr.statusText);
            submitButton.classList.add('enabled');
            submitButton.textContent = 'Upload Files';
        }
    };

    xhr.onerror = () => {
        window._isUploading = false;
        alert('Network error during upload');
        submitButton.classList.add('enabled');
        submitButton.textContent = 'Upload Files';
    };

    xhr.send(formData);
});
</script>
""" + render_receiver_session_script() + """
</body>
</html>"""
    return html
