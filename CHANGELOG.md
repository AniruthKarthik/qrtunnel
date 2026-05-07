# Changelog

All notable changes to QRTunnel are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

_Changes not yet released go here._

---

## [3.7.0] - 2026-05-07

### Added
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
