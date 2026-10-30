# Changelog

All notable changes to QRTunnel are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

_Changes not yet released go here._

---

## [3.8.4] - 2026-10-30

### Fixed
- **Bauhaus Dashboard Layout & Alignment**:
  - Resolved CSS Grid column blow-out by setting `minmax(0, ...)` tracks and `min-width: 0` on workspace panes, preventing long filenames from overflowing `.app-frame`.
  - Fixed application frame height sizing and eliminated bottom border truncation through action buttons.
  - Corrected responsive breakpoint to `@media (max-width: 820px)` for seamless single-column layout on smaller viewports.
  - Mathematical subpixel alignment for QR monolith, 4-box access code, and URL copy strip.

### Added
- **Structured Transfer Session Details**: Added a Bauhaus metadata panel to the outgoing transfer view displaying active tunnel mode, port, PIN security status, and working directory.

---

## [3.8.1] - 2026-10-30

### Changed
- Removed bottom footer text and port indicator from host dashboard for a cleaner, distraction-free interface.

### Added
- Complete Bauhaus-inspired UI/UX redesign across all host and client interfaces:
  - Bauhaus Design System (`src/qrtunnel/ui/theme.py`) featuring authentic color palette (warm ivory `#F8F6F0`, deep charcoal ink `#111215`, cadmium red `#D22626`, cobalt blue `#164785`, chrome ochre `#E5A110`).
  - Unified desktop host dashboard (`src/qrtunnel/ui/dashboard.py`) with streamlined 3-tab navigation (Send, Receive, History).
  - Interactive vector QR logo pointing to the creator's GitHub repository (`https://github.com/AniruthKarthik/qrtunnel`).
  - Asymmetric desktop workspace grid with prominent QR monolith and Bauhaus corner registration brackets.
  - Dedicated 4-box monospaced Access Code card for high visibility.
  - Real-time telemetry dashboard with live progress bar, speed readout, transferred/total bytes, and ETA estimation.
  - Interactive transfer history panel powered by `/api/history` with filtering, audit logging, and one-click history clearing (`POST /api/history/clear`).
  - Direct inline port selector and synchronization across Send and Receive workflows.
  - Redesigned mobile client download page (`src/qrtunnel/ui/download.py`) with itemized selection and streaming zip bundling.
  - Redesigned mobile client upload page (`src/qrtunnel/ui/upload.py`) with live speed tracking and multi-file dropzone.
  - Redesigned security check page (`src/qrtunnel/ui/login.py`) with geometric lock iconography and 4-digit code entry.
  - Redesigned upload receipt page (`src/qrtunnel/ui/success.py`) and session closed overlay (`src/qrtunnel/ui/session.py`).
  - Comprehensive design documentation in `DESIGN.md`.
- Real-time transfer progress bars in TUI for both uploads and downloads.
- On-the-fly ZIP archive bundling for multi-file/directory downloads.
- Local transfer history logging with `qrtunnel history` command.
- SHA256 integrity checksums displayed after every transfer.
- Windows-specific install hints for `ngrok` (via `winget`).
- `--no-qr` flag for headless and CI environments.
- `--expire` flag for automatic server shutdown after a timeout.

### Fixed
- Robust random port selection with availability checking.
- Improved LAN IP detection preferring physical interfaces over virtual/loopback.
- Early validation of file paths and directory write permissions.
- Reliable cleanup of background processes and ports on Ctrl+C (SIGINT).

### Removed
- Cloudflare tunnel backend (experimental).

---

## [3.5.1] - 2026-02-04

### Fixed
- Minor stability fixes (details to be backfilled by maintainer)

## [3.5.0]

### Added
- Interactive TUI with arrow-key navigation
- Smart mode: auto-detects LAN vs tunnel based on client network
- LAN OTP security (6-digit passcode)

## [3.0.0]

### Added
- ngrok support as default tunnel on Windows
- Randomized port selection (20000–60000)

## [2.0.0]

### Added
- `send` and `receive` subcommands
- SSH tunneling via `localhost.run`

## [1.0.0]

### Added
- Initial release: basic QR code file sharing over LAN
