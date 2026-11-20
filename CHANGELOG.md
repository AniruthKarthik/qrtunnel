# Changelog

All notable changes to QRTunnel are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

_Changes not yet released go here._

---

## [3.8.6] - 2026-11-20

### Security
- **Reverse Proxy & Tunnel Request Authentication**:
  - Enforced strict request authentication and admin endpoint restriction on reverse-proxy and tunnel connections via `is_local_request()`, preventing traffic forwarded over loopback (`127.0.0.1`) from bypassing authentication.
- **Cross-Site Scripting (XSS) Prevention**:
  - Strictly sanitized user filenames using `html.escape` in server-rendered download and upload receipt pages.
  - Implemented `escapeHtml()` in Bauhaus dashboard JavaScript before inserting filenames or client IPs into DOM `innerHTML`.
- **Client IP Header Validation**:
  - Validated client IP candidate headers (`CF-Connecting-IP`, `X-Forwarded-For`, `X-Real-IP`) with `ipaddress.ip_address` before trusting values, preventing header spoofing and injection into audit history logs.
- **Login Rate Limiting & Timing Attack Hardening**:
  - Introduced `LoginRateLimiter` enforcing a 60-second lockout after 5 consecutive failed PIN attempts.
  - Hardened PIN verification against timing attacks using `hmac.compare_digest`.
  - Migrated OTP generation from `random.randint` to cryptographically secure `secrets.randbelow`.
- **Eliminated Unverified Remote Downloads**:
  - Removed silent remote binary download of `cloudflared` from GitHub releases over unverified urllib, replacing it with clear manual installation guidance.

### Fixed
- **Concurrent Stream Tracking**:
  - Differentiated concurrent client transfer sessions by unique `stream_id` and validated real client IP, preventing reverse-proxy tunnels from coalescing separate transfers into a single stream.
- **Resilient File Streaming on Non-Standard Filesystems**:
  - Added graceful fallback to chunked streaming when `os.sendfile` raises `OSError` (e.g. on FUSE, SSHFS, NFS, or ecryptfs mounts).
- **Streaming Zip64 Header Size Parity**:
  - Synchronized Zip64 boundary threshold pre-calculation with the streaming writer to ensure `Content-Length` matches the streamed byte count.
- **Thread-Safe Transfer History & Hotspot Persistence**:
  - Added mutex locking (`_history_lock`) and atomic temporary-file replacement in `history.py` and `hotspot.py`, preventing race conditions and corrupted JSON files under concurrent transfers.
- **Non-TTY and Non-Blocking Keyboard Input**:
  - Safeguarded `_read_key_unix` against `termios.tcgetattr` ioctl crashes when stdin is non-interactive or redirected.
  - Implemented non-blocking `msvcrt.kbhit()` polling with a 150ms timeout on Windows, allowing timeout expiration (`--expire`) and synchronization loops to proceed without keypresses.
- **Session Lifecycle & Staging GC Preservation**:
  - Removed premature `beforeunload` and `pagehide` session teardown hooks from dashboard JavaScript, preventing routine page refreshes (F5) or mobile tab switching from aborting transfers.
  - Fixed startup/routine garbage collection to preserve active staging files owned by the running process (`owner_pid != current_pid`).
- **CLI Argument Preservation**:
  - Preserved numeric filenames (e.g., `-8080`) when existing on disk and added POSIX `--` delimiter awareness in CLI custom port pre-processing.
- **Network Interface & LAN Filtering**:
  - Corrected ARP table parsing in `is_same_lan` to match the exact IP column, eliminating substring match false positives.
  - Filtered out container virtual interfaces (Podman) during LAN IP detection.
- **Null Safety in Server Endpoints**:
  - Added guards in `serve_single_file` and `serve_zip_archive` when `file_paths` is `None` in receive-only mode, returning HTTP 404 instead of raising an unhandled 500 error.
- **Pinggy SSH Tunnel Command Formatting**:
  - Fixed missing f-string formatting in fallback pinggy.io SSH tunnel command.

### Packaging & Tests
- Cleaned local developer paths (`file://`) and stray freeze artifacts (`e==1.4.5`) from `requirements.txt`.
- Configured `pythonpath = ["src"]` in `pyproject.toml` pytest options for reliable out-of-tree test execution.
- Added comprehensive test suites for packaging consistency, keyboard input, LAN subnet matching, and tunnel test isolation.

---

## [3.8.5] - 2026-10-31

### Added
- **Automated Web UI Staging Disk Lifecycle Management**:
  - Automatically sweeps and deletes temporary staged upload files in `~/.qrtunnel/staged/` whenever a transfer session completes, the user clicks "Stop Transfer & Close", the browser window is closed (`beforeunload` beacon), the terminal process exits (`q` or Ctrl+C), or servers shut down.
  - Startup garbage collection: automatically detects and reclaims orphaned staging directories left behind by prior ungraceful terminations (e.g. system reboot or `kill -9`), while safely protecting active transfers running in other concurrent instances using PID validation.
- **Dedicated Cleanup CLI Command (`qrtunnel clean` / `qrtunnel cleanup`)**:
  - Manually reclaim disk space by purging all temporary staged transfer directories, with optional `--all` flag to also clear transfer history.
  - Formatted byte reporting displays exact disk space reclaimed.

### Security & Safety
- **Strict User File Isolation**:
  - Path traversal and path isolation guards (`Path.relative_to`) ensure original files shared via CLI or receiver destination folders are never deleted or modified during cleanup. Staging cleanup is strictly confined to subdirectories of `~/.qrtunnel/staged/`.

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
