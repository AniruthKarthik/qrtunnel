# QRTunnel Design System & UX Architecture Specification (`DESIGN.md`)

## Executive Summary

This document specifies the complete visual, architectural, and interaction redesign of **QRTunnel** based on the **Bauhaus design language**. Moving away from generic AI-generated templates (excessive rounded cards, glowing borders, gratuitous gradients, and glassmorphism), QRTunnel is transformed into a disciplined, functional, and visually distinctive desktop utility.

The redesign covers the entire application surface across host and client contexts:
1. **Host Dashboard:** Unified multi-tab desktop workspace supporting **Send**, **Receive**, and **History** with inline port configuration and history clearing.
2. **Mobile / Client Portal:** Responsive **Download**, **Upload**, **Security Check (PIN Entry)**, **Upload Complete (Receipt)**, and **Session Closed Overlay** screens.
3. **Modular Frontend Architecture:** Decoupled presentation layer in `src/qrtunnel/ui/` with clear design tokens, component modularity, and zero CPU rendering overhead.

---

## 1. Design Philosophy: The Bauhaus Movement in Software

The Bauhaus school (1919–1933) founded by Walter Gropius established that **form follows function** (*Form folgt Funktion*). In software engineering and interface architecture, this principle translates into prioritizing utility, clarity, and structural balance over superficial decoration.

### Core Bauhaus Principles Applied to QRTunnel:
- **Function Over Decoration:** Every visual line, surface, and color choice conveys state or interaction. Gratuitous drop shadows, neon accents, and decorative cards have been eliminated.
- **Geometric Simplicity & Orthogonal Grids:** Components align to a disciplined 8pt grid with sharp geometric silhouettes (clean rectangular blocks, solid rules, and unrounded structural panels).
- **Asymmetric Balanced Composition:** On desktop viewports, an asymmetric two-column workspace balances the primary file staging and controls against the monolithic QR stage and telemetry readout.
- **Purposeful Typography & Strong Contrast:** Geometric sans-serif grotesk typefaces paired with high-precision tabular monospace typography for all technical metrics (speeds, IP addresses, ports, checksums, transfer bytes, and access codes).
- **Mathematical Color Harmony:** An authentic palette grounded in traditional Bauhaus primaries (Cadmium Red, Cobalt Blue, Chrome Ochre) on a warm off-white ivory canvas.

---

## 2. Color Palette & Design Tokens

QRTunnel uses a predominantly light, warm tactile theme reminiscent of classic Bauhaus editorial prints and architectural drafting paper.

### 2.1 Color Tokens (`src/qrtunnel/ui/theme.py`)

| Token | Hex Value | Role & Usage |
|---|---|---|
| `--bh-bg` | `#F8F6F0` | Warm ivory canvas / application background |
| `--bh-surface` | `#FFFFFF` | Crisp white primary functional surface for content panels |
| `--bh-surface-alt` | `#F1ECE1` | Recessed warm well for secondary sections and table headers |
| `--bh-surface-sunken` | `#E7E2D6` | Sunken progress track and inactive input wells |
| `--bh-ink` | `#111215` | Deep near-black charcoal for primary text, bold rules, and brand marks (Contrast ratio > 16:1) |
| `--bh-ink-secondary` | `#484A51` | Neutral charcoal for secondary descriptions and labels |
| `--bh-ink-muted` | `#787A82` | Medium gray for structural micro-labels and table column headers |
| `--bh-red` | `#D22626` | Bauhaus Cadmium Red for destructive actions (*Stop Transfer*), errors, and session termination |
| `--bh-red-subtle` | `#FDF2F2` | Tinted background for error alerts |
| `--bh-blue` | `#164785` | Bauhaus Cobalt Blue for primary calls to action (*Share Files*), links, and active progress |
| `--bh-blue-subtle` | `#EEF4FA` | Tinted background for active selections and notices |
| `--bh-yellow` | `#E5A110` | Bauhaus Chrome Ochre for warnings, fallback indicators, and auxiliary states |
| `--bh-yellow-subtle`| `#FEF9EB` | Tinted background for caution banners |
| `--bh-green` | `#15803D` | Functional forest emerald for transfer completion badges and verification confirmations |
| `--bh-border` | `#111215` | Solid 1.5px / 2px geometric boundary lines |
| `--bh-border-subtle`| `#D8D4CA` | Clean mechanical divider rules (1px) |

---

## 3. Typographic System

Typography is the backbone of the Bauhaus visual hierarchy. QRTunnel employs a dual-font typographic hierarchy:

### 3.1 Font Stacks
1. **Geometric Grotesk Stack (UI / Headings / Labels):**
   ```css
   font-family: -apple-system, BlinkMacSystemFont, "Plus Jakarta Sans", "Inter", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
   ```
2. **Precision Monospace Stack (Technical Metadata / Numbers / Codes):**
   ```css
   font-family: "JetBrains Mono", "SF Mono", "Fira Code", Menlo, Monaco, Consolas, "Courier New", monospace;
   font-feature-settings: "tnum" 1, "zero" 1;
   ```

### 3.2 Typographic Hierarchy & Scale

- **Brand Wordmark:** 18px, Extra Bold (800), Uppercase, `letter-spacing: 0.08em`
- **Primary Section Headings:** 20px – 22px, Extra Bold (800), Uppercase, `letter-spacing: -0.3px`
- **Category Micro-labels:** 10.5px, Bold (700), Uppercase, `letter-spacing: 0.12em`, `color: var(--bh-ink-muted)`
- **Body & Form Copy:** 13px – 13.5px, Regular/Medium (400/500), `line-height: 1.45`
- **Technical Readouts (Telemetry, Sizes, Speed):** 11.5px – 12.5px, Bold (700) Monospace
- **Access Code Display:** 26px, Extra Bold (800) Monospace in geometric digit boxes

---

## 4. Layout & Information Architecture

### 4.1 Master Frame & Navigation
The desktop host UI is framed in a solid structural container (`max-width: 920px`) with sharp corners, featuring:
- **Brand Top Bar:** Interactive vector QR emblem (encoding and linking directly to the project GitHub repository `https://github.com/AniruthKarthik/qrtunnel`), uppercase logotype `QRTUNNEL`, version tag `v3.8.0`, and a live geometric status pip (`ONLINE // LAN: 192.168.1.10:6969`).
- **Architectural Segmented Navigation:**
  - `[ ↗ SEND FILES ]`: Host-to-client dispatch workflow with inline port controls.
  - `[ ↘ RECEIVE FILES ]`: Client-to-host ingest workflow with inline port controls.
  - `[ ◷ HISTORY ]`: Audit log and manifest of all previous transfers with one-click purge.

### 4.2 Workspace Layout (Asymmetric Two-Column Grid)
On desktop viewports (`min-width: 768px`), the workspace divides mathematically into:
1. **Primary Pane (58% width):** File dropzone, staged files manifest table, tunnel mode selector grid, inline port configuration, and primary action buttons.
2. **Stage Pane (42% width):** Architectural QR frame with corner registration marks, 4-box monospaced Access Code card, target URL copy strip, and live real-time telemetry dashboard.

On mobile and narrow desktop windows (`< 768px`), the layout stacks into a single vertical column without horizontal clipping or overflow.

---

## 5. Screen & Workflow Specifications

### 5.1 Host Send Workflow (`/sender`)
- **Staging Dropzone:** High-contrast geometric dropzone with crosshair alignment, drag-and-drop feedback, and native multi-file picker.
- **Staged Files Manifest:** Table displaying staged files with formatted sizes (`24.5 MB`), individual remove actions, and batch total counter.
- **Tunnel Mode Grid:** 4 modular Bauhaus tiles (`LAN`, `CLOUDFLARE`, `SSH`, `NGROK`) with transport specifications (`Wi-Fi`, `Tunnel`, `Port 22/443`, `Secure`).
- **Inline Port Selector:** Monospaced port input with inline validation and instant asynchronous update (`/api/sender/port`).
- **QR Monolith:** High-contrast QR presentation frame with Bauhaus corner brackets.
- **4-Box Access Code:** Four separate bordered digit boxes displaying the 4-digit PIN for immediate readability from across a room.
- **Telemetry Dashboard:** Live progress bar, transferred / total bytes, speed readout (`MB/s`), completion percentage, and estimated time remaining (`ETA mm:ss`).

### 5.2 Host Receive Workflow (`/receive`)
- **Ingest Mode Selector:** Direct mode switching between local LAN and public WAN tunnels with instant loading spinner and feedback.
- **Incoming Transfers Manifest:** Workspace directory badge (`📁 workspace`), live in-flight progress bar for active uploads, and real-time list of received files with size badges and timestamps.
- **Instant Connection Stage:** QR code and 4-digit Access Code directing mobile clients to the upload portal.

### 5.3 Transfer History Panel (`/sender#history`)
- Accessible via the navigation tab or `#history` hash.
- Asynchronously loads from the dedicated `/api/history` endpoint.
- Filter buttons: `[ ALL ]`, `[ SENT ]`, `[ RECEIVED ]`.
- Audit table listing Timestamp (UTC), Direction tag (`SENT` / `RECEIVED`), Filename, Formatted Size, and Remote Client IP.
- Immediate `[ CLEAR ]` audit log action with confirmation dialog and backend purging (`POST /api/history/clear`).

### 5.4 Inline Port & Network Configuration
- To maximize usability and reduce screen clutter, port binding is directly editable and visible within the Send and Receive control panels.
- Default port (`6969`) is explicitly populated and synchronized across both tabs.
- Port updates are validated and committed asynchronously via `/api/sender/port` and `/api/receiver/mode`.
- Minimalist footer displays active listening port and engine status without decorative system badges.

### 5.5 Mobile Client Screens
- **Download Page (`/` or `/download`):** Bauhaus header, file count pill, `[ Select All ]` toggle, itemized file list with checkboxes and individual download arrows (`dl-single-btn`), batch `[ DOWNLOAD SELECTED (.ZIP) ]` action, and zipping progress bar.
- **Upload Page (`/` or `/upload`):** Dropzone with file preview list, individual file sizes, upload progress bar with live upload speed and percentage, and `[ UPLOAD FILES ]` action.
- **Security Check Page (`/login`):** Bauhaus lock emblem, instructions, autofocus numeric 4-digit input with character tracking, and `[ VERIFY CODE ]` action.
- **Upload Complete Page (Success):** Bauhaus checkmark emblem, itemized receipt with received filenames and formatted sizes, and `[ UPLOAD MORE FILES ]` action.
- **Session Closed Overlay:** High-contrast full-screen Bauhaus notification indicating that the session has safely ended.

---

## 6. Interaction Design & Micro-interactions

- **Restrained Transitions:** All interactive transitions are fast and lightweight (`0.12s ease`). No spring physics, 3D flips, or blur animations that consume CPU during heavy file I/O.
- **Direct Targeted DOM Updates:** Live progress updates via Server-Sent Events (SSE) directly modify specific DOM nodes (`textContent`, `style.width`), avoiding costly component tree rerenders.
- **Keyboard Navigation:**
  - Full tab-index traversal with high-contrast `:focus-visible` outlines (`2px solid var(--bh-ink)` with `2px offset`).
  - Enter key automatically triggers port configuration updates.
  - Auto-focus on PIN verification fields.
- **Copy Link Action:** Click-to-copy button provides immediate tactile confirmation (`"COPIED!"`) before reverting cleanly.

---

## 7. Performance & Rendering Constraints

The UI redesign adheres strictly to the performance achievements documented in `PERFORMANCE.md`:
1. **Zero Render Overhead:** CSS is purely native; no heavy third-party CSS or JS frameworks are loaded.
2. **Non-blocking Telemetry:** Progress telemetry throttled on backend to $\ge 200\text{ ms}$ intervals, preventing DOM thrashing.
3. **Bandwidth Efficiency:** Zero external font or icon downloads; all SVG vectors and typography stacks are self-contained and use system-native geometric fonts.

---

## 8. Frontend Architecture & Modularization

The presentation layer is cleanly decoupled into `src/qrtunnel/ui/`:

```
src/qrtunnel/ui/
├── __init__.py      # Public interface exports
├── dashboard.py     # Bauhaus unified desktop application (Send, Receive, History)
├── download.py      # Client download page & selective zip builder
├── login.py         # Security check 4-digit code entry
├── session.py       # Session closed overlay & status poller
├── success.py       # Upload complete receipt page
├── theme.py         # Bauhaus CSS variables, design tokens, and geometric SVG icons
└── upload.py        # Client multipart upload page with live progress
```

This modularization reduced `src/qrtunnel/server.py` by **1,788 lines**, isolating server routing and transfer mechanics from presentation markup.

