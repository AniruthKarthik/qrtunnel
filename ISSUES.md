# QRTunnel — Pre-filed Issues Reference

Copy each block below to create issues on GitHub. Labels are listed at the top of each issue.

---

## BUGS

---

### Issue: Port not checked for availability before binding — silent crash

**Labels:** `bug`

**Description:**

A random port is selected from 20000–60000 but never checked for availability before the server binds to it. If the port is already in use, the server crashes with an unhandled `OSError: [Errno 98] Address already in use`.

**Expected behavior:** Check port availability before binding. If occupied, select another port and retry (up to N attempts).

---

### Issue: LAN IP detection returns loopback or wrong interface on multi-NIC machines

**Labels:** `bug`

**Description:**

On machines with multiple network interfaces (VPN, Docker bridge, loopback, Ethernet + Wi-Fi), the LAN IP detection may return `127.0.0.1` or a non-LAN interface IP, making the LAN QR code point to an unreachable address.

**Expected behavior:** Prefer the first non-loopback, non-Docker, non-VPN IPv4 address. Fall back to socket-based detection.

---

### Issue: No write permission check on receive destination before starting server

**Labels:** `bug`

**Description:**

`qrtunnel receive ./downloads` starts the HTTP server before verifying that the destination directory is writable. If the directory doesn't exist or has wrong permissions, the error only surfaces when a file upload is attempted.

**Expected behavior:** Validate destination path exists and is writable at startup. Create it if missing. Fail early with a clear error if not writable.

---

### Issue: Ctrl+C leaves server process running (zombie server)

**Labels:** `bug`

**Description:**

Interrupting `qrtunnel` with `Ctrl+C` does not reliably terminate the background HTTP server and/or SSH subprocess in all code paths. Ports remain occupied.

**Expected behavior:** Register `signal.SIGINT` and `atexit` handlers to cleanly terminate all subprocesses and release ports on exit.

---

### Issue: LAN OTP never invalidated after first use

**Labels:** `bug`, `security`

**Description:**

The 6-digit OTP for LAN mode is static for the entire session. Any device that obtains the passcode can continue accessing the server indefinitely during the session.

**Expected behavior:** Optionally invalidate OTP after first successful use, or at minimum document this limitation clearly in the UI and README.

---

## GOOD FIRST ISSUES

---

### Issue: Add `--no-qr` flag for headless/CI environments

**Labels:** `good first issue`, `enhancement`

**Description:**

In CI or headless environments, the QR code renders as garbage. Add a `--no-qr` flag that suppresses QR output and prints only the URL.

---

### Issue: Validate file paths before starting server

**Labels:** `good first issue`, `bug`

**Description:**

`qrtunnel send nonexistent.txt` starts the server before discovering the file doesn't exist. Validate all paths at argument parse time and fail with a clear message before any server is started.

---

## FEATURES / ENHANCEMENTS

---

### Issue: Add Cloudflare Tunnel (`cloudflared`) as tunnel backend

**Labels:** `enhancement`

**Description:**

Add `cloudflared` as an optional third tunnel backend alongside SSH and ngrok. `cloudflared tunnel --url` requires no account for quick tunnels. This is useful where `localhost.run` is blocked or unreliable.

---

### Issue: Transfer progress bar in TUI

**Labels:** `enhancement`

**Description:**

TUI currently shows no transfer progress. Add a progress bar displaying bytes transferred, total size, percentage, and estimated time remaining during active transfers.

---

### Issue: Bundle multiple files as a zip on-the-fly

**Labels:** `enhancement`

**Description:**

When sending a directory or multiple files, stream a zip archive instead of requiring the recipient to download files individually. The zip should be created in-memory (no temp file) using `zipfile.ZipFile` with `io.BytesIO`.

---

### Issue: Display SHA256 checksum post-transfer

**Labels:** `enhancement`

**Description:**

After a transfer completes (send or receive), display the SHA256 checksum of the transferred file(s) in the terminal so users can verify integrity without a separate tool.

---

### Issue: `--expire` flag to auto-shutdown server

**Labels:** `enhancement`

**Description:**

Add `--expire <seconds>` (or `--once` for single-download shutdown) to auto-terminate the server after a timeout or after the first successful download. Prevents long-lived accidental exposure.

---

### Issue: Transfer log to local JSON file

**Labels:** `enhancement`

**Description:**

Optionally log all transfers (filename, size, timestamp, client IP, direction) to `~/.qrtunnel/history.json`. Add `qrtunnel history` subcommand to display recent transfers.

---

### Issue: Windows — prompt to install ngrok via winget if missing

**Labels:** `enhancement`

**Description:**

On Windows, if ngrok is not found, detect whether `winget` is available and prompt: `ngrok not found. Run: winget install ngrok.ngrok` with an option to open a browser to the ngrok download page.

---

## DOCUMENTATION

---

### Issue: README missing TUI screenshot

**Labels:** `documentation`

**Description:**

The README describes the TUI but has no screenshot. Add a terminal screenshot (use `carbon.sh`, `termshot`, or a plain PNG) showing the TUI in file-selection mode.

---

### Issue: README missing system requirements

**Labels:** `documentation`

**Description:**

Add a requirements table to the README:

| Requirement | Minimum |
|---|---|
| Python | 3.8+ |
| OS | Linux, macOS, Windows |
| `ssh` binary | Required for SSH mode (Linux/macOS) |
| ngrok | Required for ngrok mode |

---

### Issue: README missing known limitations section

**Labels:** `documentation`

**Description:**

Add a **Limitations** section covering:

- `localhost.run` may enforce rate limits or session duration limits.
- ngrok free tier limits: 1 tunnel at a time, bandwidth caps.
- No authentication on the download URL (any device with the URL can download).
- LAN OTP is not invalidated after first use.
- Not suitable for sensitive/regulated data.

---

### Issue: README missing security model explanation

**Labels:** `documentation`

**Description:**

Add a **Security** section explaining what protections exist (OTP, randomized port), what is not protected (no auth on tunnel URL, third-party tunnel traffic), and the intended threat model (convenience sharing, not secure transfer).

---

## INFRASTRUCTURE / CI

---

### Issue: Expand test suite — tunnel selection logic

**Labels:** `testing`

**Description:**

The `tests/` directory exists but coverage is likely minimal. Add unit tests for:

- Port availability check logic
- LAN IP selection (mock network interfaces)
- File path validation
- CLI argument parsing
