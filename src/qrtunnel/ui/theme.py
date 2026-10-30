"""Bauhaus Design System - Design tokens, CSS variables, and shared SVG icons."""

# Bauhaus Design Tokens
BAUHAUS_CSS = """
:root {
    /* Palette: Traditional Bauhaus Color Wheel */
    --bh-bg: #F8F6F0;           /* Warm ivory / canvas */
    --bh-surface: #FFFFFF;      /* Clean functional surface */
    --bh-surface-alt: #F1ECE1;  /* Structural warm well */
    --bh-surface-sunken: #E7E2D6;
    --bh-ink: #111215;          /* Deep near-black charcoal */
    --bh-ink-secondary: #484A51;/* Secondary charcoal */
    --bh-ink-muted: #787A82;    /* Structural label gray */
    --bh-ink-faint: #A8AAB2;    /* Faint dividers & borders */

    /* Bauhaus Primary Accents */
    --bh-red: #D22626;          /* Bauhaus Cadmium Red */
    --bh-red-dark: #AC1B1B;
    --bh-red-subtle: #FDF2F2;
    --bh-blue: #164785;         /* Bauhaus Cobalt Blue */
    --bh-blue-dark: #0E3362;
    --bh-blue-subtle: #EEF4FA;
    --bh-yellow: #E5A110;       /* Bauhaus Warm Ochre / Chrome Yellow */
    --bh-yellow-subtle: #FEF9EB;
    --bh-green: #15803D;        /* Clean functional green */
    --bh-green-subtle: #F0FDF4;

    /* Legacy compatibility token for light-theme tests */
    --bh-gray-light: #f8fafc;

    /* Structural Grid & Borders */
    --bh-border: #111215;
    --bh-border-width: 1.5px;
    --bh-border-heavy: 2px;
    --bh-border-subtle: #D8D4CA;

    /* Typography */
    --bh-font-sans: -apple-system, BlinkMacSystemFont, "Plus Jakarta Sans", "Inter", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    --bh-font-mono: "JetBrains Mono", "SF Mono", "Fira Code", Menlo, Monaco, Consolas, "Courier New", monospace;

    /* Spacing Grid (8pt baseline) */
    --bh-space-1: 4px;
    --bh-space-2: 8px;
    --bh-space-3: 12px;
    --bh-space-4: 16px;
    --bh-space-5: 20px;
    --bh-space-6: 24px;
    --bh-space-8: 32px;
    --bh-space-12: 48px;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}

body {
    font-family: var(--bh-font-sans);
    background-color: var(--bh-bg);
    color: var(--bh-ink);
    min-height: 100vh;
    line-height: 1.45;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

a, a:hover, a:visited, a:focus, a:active {
    text-decoration: none !important;
    color: inherit;
    outline: none;
}

button, input, select, textarea {
    font-family: inherit;
    font-size: inherit;
    color: inherit;
    outline: none;
}

:focus-visible {
    outline: 2px solid var(--bh-ink) !important;
    outline-offset: 2px !important;
}

/* Monospace technical data */
.mono {
    font-family: var(--bh-font-mono);
    font-feature-settings: "tnum" 1, "zero" 1;
}

/* Micro-label style */
.micro-label {
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--bh-ink-secondary);
}

/* Geometric Status Pip */
.status-pip {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: var(--bh-green);
    margin-right: 6px;
}
.status-pip.active { background: var(--bh-blue); }
.status-pip.warn { background: var(--bh-yellow); }
.status-pip.stop { background: var(--bh-red); }
"""

# Reusable SVG vector icons (clean geometric stroke)
ICONS = {
    "brand_emblem": """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="2" y="2" width="9" height="9" fill="#D22626"/>
        <circle cx="16.5" cy="6.5" r="4.5" fill="#164785"/>
        <polygon points="12,13 21,22 3,22" fill="#E5A110"/>
    </svg>""",
    "send": """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>""",
    "receive": """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>""",
    "history": """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>""",
    "settings": """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>""",
    "copy": """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="square"><rect x="9" y="9" width="13" height="13" rx="0" ry="0"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>""",
    "link": """<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>""",
    "lock": """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><rect x="3" y="11" width="18" height="11"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>""",
    "check": """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="square"><polyline points="20 6 9 17 4 12"/></svg>""",
    "file": """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="square"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>""",
    "folder": """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="square"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>""",
    "close": """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>""",
    "stop": """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="square"><circle cx="12" cy="12" r="10"/><rect x="9" y="9" width="6" height="6" fill="currentColor"/></svg>""",
    "upload_cloud": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="square"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>""",
}
