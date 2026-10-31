"""Bauhaus Session Management - Session closed notification overlay and polling/SSE watcher."""

def render_receiver_session_script() -> str:
    return """<script>
(function() {
    function showSessionClosed() {
        if (document.getElementById('session-closed-overlay')) return;
        var overlay = document.createElement('div');
        overlay.id = 'session-closed-overlay';
        overlay.style.position = 'fixed';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100vw';
        overlay.style.height = '100vh';
        overlay.style.background = '#F8F6F0';
        overlay.style.display = 'flex';
        overlay.style.flexDirection = 'column';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.padding = '24px 16px';
        overlay.style.zIndex = '999999';
        overlay.style.boxSizing = 'border-box';
        overlay.style.fontFamily = '-apple-system,BlinkMacSystemFont,"Plus Jakarta Sans","Inter","Segoe UI",Roboto,sans-serif';
        overlay.innerHTML = `
          <div style="background:#FFFFFF;border:2px solid #111215;padding:40px 32px;max-width:440px;width:100%;text-align:center;box-shadow:none;">
            <div style="display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;background:#111215;color:#FFFFFF;margin-bottom:20px;">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </div>
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.14em;color:#787A82;margin-bottom:8px;">TERMINATED</div>
            <h1 style="font-size:22px;font-weight:800;color:#111215;margin-bottom:10px;letter-spacing:-0.4px;text-transform:uppercase;">Session Closed</h1>
            <p style="font-size:13.5px;color:#484A51;line-height:1.5;margin:0 0 24px;">The session has closed. You can safely close this window.</p>
            <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;font-weight:600;color:#787A82;border-top:1px solid #D8D4CA;padding-top:14px;letter-spacing:0.05em;">QRTUNNEL // DISCONNECTED</div>
          </div>
        `;
        document.body.appendChild(overlay);
    }

    try {
        var es = new EventSource('/api/receiver/events');
        es.addEventListener('close', function(e) {
            try {
                var d = JSON.parse(e.data);
                if (d && d.closed) showSessionClosed();
            } catch(err) {
                showSessionClosed();
            }
        });
    } catch(e) {}

    var failedCount = 0;
    var checkInterval = setInterval(function() {
        if (window._isUploading) return;
        fetch('/api/session/status', { cache: 'no-store' })
            .then(function(res) {
                if (!res.ok) throw new Error('status ' + res.status);
                return res.json();
            })
            .then(function(data) {
                if (data && data.closed) {
                    showSessionClosed();
                    clearInterval(checkInterval);
                } else {
                    failedCount = 0;
                }
            })
            .catch(function() {
                if (window._isUploading) return;
                failedCount++;
                if (failedCount >= 10) {
                    showSessionClosed();
                    clearInterval(checkInterval);
                }
            });
    }, 3000);
})();
</script>"""

