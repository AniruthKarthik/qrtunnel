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
    "brand_emblem": """<svg width="28" height="28" viewBox="0 0 33 33" fill="none" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
    <rect width="33" height="33" fill="#FFFFFF"/>
    <path d="M2,2H3V3H2zM3,2H4V3H3zM4,2H5V3H4zM5,2H6V3H5zM6,2H7V3H6zM7,2H8V3H7zM8,2H9V3H8zM10,2H11V3H10zM11,2H12V3H11zM13,2H14V3H13zM14,2H15V3H14zM15,2H16V3H15zM19,2H20V3H19zM24,2H25V3H24zM25,2H26V3H25zM26,2H27V3H26zM27,2H28V3H27zM28,2H29V3H28zM29,2H30V3H29zM30,2H31V3H30zM2,3H3V4H2zM8,3H9V4H8zM10,3H11V4H10zM12,3H13V4H12zM15,3H16V4H15zM19,3H20V4H19zM20,3H21V4H20zM21,3H22V4H21zM24,3H25V4H24zM30,3H31V4H30zM2,4H3V5H2zM4,4H5V5H4zM5,4H6V5H5zM6,4H7V5H6zM8,4H9V5H8zM10,4H11V5H10zM12,4H13V5H12zM13,4H14V5H13zM15,4H16V5H15zM18,4H19V5H18zM20,4H21V5H20zM21,4H22V5H21zM24,4H25V5H24zM26,4H27V5H26zM27,4H28V5H27zM28,4H29V5H28zM30,4H31V5H30zM2,5H3V6H2zM4,5H5V6H4zM5,5H6V6H5zM6,5H7V6H6zM8,5H9V6H8zM11,5H12V6H11zM12,5H13V6H12zM14,5H15V6H14zM15,5H16V6H15zM19,5H20V6H19zM21,5H22V6H21zM22,5H23V6H22zM24,5H25V6H24zM26,5H27V6H26zM27,5H28V6H27zM28,5H29V6H28zM30,5H31V6H30zM2,6H3V7H2zM4,6H5V7H4zM5,6H6V7H5zM6,6H7V7H6zM8,6H9V7H8zM10,6H11V7H10zM18,6H19V7H18zM19,6H20V7H19zM21,6H22V7H21zM24,6H25V7H24zM26,6H27V7H26zM27,6H28V7H27zM28,6H29V7H28zM30,6H31V7H30zM2,7H3V8H2zM8,7H9V8H8zM11,7H12V8H11zM14,7H15V8H14zM16,7H17V8H16zM19,7H20V8H19zM24,7H25V8H24zM30,7H31V8H30zM2,8H3V9H2zM3,8H4V9H3zM4,8H5V9H4zM5,8H6V9H5zM6,8H7V9H6zM7,8H8V9H7zM8,8H9V9H8zM10,8H11V9H10zM12,8H13V9H12zM14,8H15V9H14zM16,8H17V9H16zM18,8H19V9H18zM20,8H21V9H20zM22,8H23V9H22zM24,8H25V9H24zM25,8H26V9H25zM26,8H27V9H26zM27,8H28V9H27zM28,8H29V9H28zM29,8H30V9H29zM30,8H31V9H30zM11,9H12V10H11zM12,9H13V10H12zM15,9H16V10H15zM2,10H3V11H2zM5,10H6V11H5zM6,10H7V11H6zM7,10H8V11H7zM8,10H9V11H8zM9,10H10V11H9zM10,10H11V11H10zM13,10H14V11H13zM14,10H15V11H14zM16,10H17V11H16zM17,10H18V11H17zM19,10H20V11H19zM23,10H24V11H23zM26,10H27V11H26zM28,10H29V11H28zM29,10H30V11H29zM30,10H31V11H30zM4,11H5V12H4zM6,11H7V12H6zM14,11H15V12H14zM15,11H16V12H15zM16,11H17V12H16zM17,11H18V12H17zM21,11H22V12H21zM23,11H24V12H23zM25,11H26V12H25zM26,11H27V12H26zM28,11H29V12H28zM29,11H30V12H29zM4,12H5V13H4zM5,12H6V13H5zM6,12H7V13H6zM8,12H9V13H8zM9,12H10V13H9zM11,12H12V13H11zM13,12H14V13H13zM15,12H16V13H15zM17,12H18V13H17zM18,12H19V13H18zM19,12H20V13H19zM25,12H26V13H25zM26,12H27V13H26zM28,12H29V13H28zM2,13H3V14H2zM4,13H5V14H4zM6,13H7V14H6zM7,13H8V14H7zM9,13H10V14H9zM10,13H11V14H10zM13,13H14V14H13zM17,13H18V14H17zM19,13H20V14H19zM20,13H21V14H20zM23,13H24V14H23zM24,13H25V14H24zM25,13H26V14H25zM27,13H28V14H27zM30,13H31V14H30zM2,14H3V15H2zM5,14H6V15H5zM6,14H7V15H6zM8,14H9V15H8zM10,14H11V15H10zM11,14H12V15H11zM12,14H13V15H12zM18,14H19V15H18zM21,14H22V15H21zM22,14H23V15H22zM24,14H25V15H24zM25,14H26V15H25zM30,14H31V15H30zM2,15H3V16H2zM3,15H4V16H3zM4,15H5V16H4zM5,15H6V16H5zM7,15H8V16H7zM10,15H11V16H10zM12,15H13V16H12zM16,15H17V16H16zM17,15H18V16H17zM19,15H20V16H19zM20,15H21V16H20zM21,15H22V16H21zM24,15H25V16H24zM25,15H26V16H25zM26,15H27V16H26zM27,15H28V16H27zM28,15H29V16H28zM29,15H30V16H29zM30,15H31V16H30zM3,16H4V17H3zM5,16H6V17H5zM6,16H7V17H6zM7,16H8V17H7zM8,16H9V17H8zM10,16H11V17H10zM11,16H12V17H11zM12,16H13V17H12zM13,16H14V17H13zM14,16H15V17H14zM16,16H17V17H16zM17,16H18V17H17zM20,16H21V17H20zM21,16H22V17H21zM22,16H23V17H22zM23,16H24V17H23zM24,16H25V17H24zM26,16H27V17H26zM28,16H29V17H28zM30,16H31V17H30zM4,17H5V18H4zM11,17H12V18H11zM14,17H15V18H14zM16,17H17V18H16zM17,17H18V18H17zM18,17H19V18H18zM20,17H21V18H20zM21,17H22V18H21zM25,17H26V18H25zM26,17H27V18H26zM28,17H29V18H28zM30,17H31V18H30zM3,18H4V19H3zM6,18H7V19H6zM8,18H9V19H8zM10,18H11V19H10zM11,18H12V19H11zM12,18H13V19H12zM15,18H16V19H15zM19,18H20V19H19zM21,18H22V19H21zM22,18H23V19H22zM23,18H24V19H23zM27,18H28V19H27zM2,19H3V20H2zM3,19H4V20H3zM4,19H5V20H4zM6,19H7V20H6zM9,19H10V20H9zM10,19H11V20H10zM14,19H15V20H14zM17,19H18V20H17zM20,19H21V20H20zM21,19H22V20H21zM26,19H27V20H26zM28,19H29V20H28zM29,19H30V20H29zM2,20H3V21H2zM3,20H4V21H3zM4,20H5V21H4zM8,20H9V21H8zM9,20H10V21H9zM10,20H11V21H10zM12,20H13V21H12zM13,20H14V21H13zM15,20H16V21H15zM17,20H18V21H17zM20,20H21V21H20zM21,20H22V21H21zM26,20H27V21H26zM27,20H28V21H27zM30,20H31V21H30zM2,21H3V22H2zM3,21H4V22H3zM6,21H7V22H6zM12,21H13V22H12zM15,21H16V22H15zM21,21H22V22H21zM24,21H25V22H24zM27,21H28V22H27zM28,21H29V22H28zM2,22H3V23H2zM3,22H4V23H3zM4,22H5V23H4zM5,22H6V23H5zM6,22H7V23H6zM8,22H9V23H8zM9,22H10V23H9zM11,22H12V23H11zM12,22H13V23H12zM13,22H14V23H13zM14,22H15V23H14zM16,22H17V23H16zM18,22H19V23H18zM19,22H20V23H19zM22,22H23V23H22zM23,22H24V23H23zM24,22H25V23H24zM25,22H26V23H25zM26,22H27V23H26zM27,22H28V23H27zM28,22H29V23H28zM29,22H30V23H29zM10,23H11V24H10zM11,23H12V24H11zM12,23H13V24H12zM13,23H14V24H13zM14,23H15V24H14zM15,23H16V24H15zM16,23H17V24H16zM17,23H18V24H17zM20,23H21V24H20zM22,23H23V24H22zM26,23H27V24H26zM27,23H28V24H27zM2,24H3V25H2zM3,24H4V25H3zM4,24H5V25H4zM5,24H6V25H5zM6,24H7V25H6zM7,24H8V25H7zM8,24H9V25H8zM10,24H11V25H10zM13,24H14V25H13zM17,24H18V25H17zM19,24H20V25H19zM20,24H21V25H20zM21,24H22V25H21zM22,24H23V25H22zM24,24H25V25H24zM26,24H27V25H26zM27,24H28V25H27zM2,25H3V26H2zM8,25H9V26H8zM10,25H11V26H10zM13,25H14V26H13zM18,25H19V26H18zM19,25H20V26H19zM21,25H22V26H21zM22,25H23V26H22zM26,25H27V26H26zM2,26H3V27H2zM4,26H5V27H4zM5,26H6V27H5zM6,26H7V27H6zM8,26H9V27H8zM10,26H11V27H10zM11,26H12V27H11zM14,26H15V27H14zM15,26H16V27H15zM16,26H17V27H16zM18,26H19V27H18zM21,26H22V27H21zM22,26H23V27H22zM23,26H24V27H23zM24,26H25V27H24zM25,26H26V27H25zM26,26H27V27H26zM27,26H28V27H27zM29,26H30V27H29zM2,27H3V28H2zM4,27H5V28H4zM5,27H6V28H5zM6,27H7V28H6zM8,27H9V28H8zM10,27H11V28H10zM12,27H13V28H12zM13,27H14V28H13zM14,27H15V28H14zM15,27H16V28H15zM16,27H17V28H16zM17,27H18V28H17zM18,27H19V28H18zM23,27H24V28H23zM30,27H31V28H30zM2,28H3V29H2zM4,28H5V29H4zM5,28H6V29H5zM6,28H7V29H6zM8,28H9V29H8zM12,28H13V29H12zM13,28H14V29H13zM16,28H17V29H16zM17,28H18V29H17zM18,28H19V29H18zM19,28H20V29H19zM20,28H21V29H20zM22,28H23V29H22zM23,28H24V29H23zM25,28H26V29H25zM26,28H27V29H26zM28,28H29V29H28zM29,28H30V29H29zM30,28H31V29H30zM2,29H3V30H2zM8,29H9V30H8zM11,29H12V30H11zM20,29H21V30H20zM24,29H25V30H24zM25,29H26V30H25zM27,29H28V30H27zM28,29H29V30H28zM30,29H31V30H30zM2,30H3V31H2zM3,30H4V31H3zM4,30H5V31H4zM5,30H6V31H5zM6,30H7V31H6zM7,30H8V31H7zM8,30H9V31H8zM10,30H11V31H10zM12,30H13V31H12zM13,30H14V31H13zM15,30H16V31H15zM17,30H18V31H17zM18,30H19V31H18zM21,30H22V31H21zM22,30H23V31H22zM24,30H25V31H24zM26,30H27V31H26z" fill="#111215"/>
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

