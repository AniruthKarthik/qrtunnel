# qrtunnel

qrtunnel is a cross-platform tool for immediate file sharing via QR codes. It utilizes SSH reverse tunneling and local networking to bridge the gap between a computer and mobile devices, enabling file transfers even behind NAT or restrictive firewalls without requiring an account.

## Features

*   **Interactive Terminal User Interface (TUI):** A keyboard-driven interface for file selection, mode configuration, and port management.
*   **Smart Mode:** Simultaneously establishes a public tunnel and a local LAN server. The recipient device automatically detects the fastest available path (LAN or WAN).
*   **High-Speed LAN Transfers:** Directly shares files over the local network for maximum speed and privacy.
*   **One-Time Password (OTP) Security:** Local network access is protected by a 6-digit passcode displayed only on the host machine.
*   **Account-Free Tunneling:** Uses SSH-based tunneling (via localhost.run) by default on Linux and macOS, requiring no registration.
*   **Cloudflare Tunnel Support:** Can use `cloudflared` quick tunnels as another account-free public backend.
*   **Ngrok Integration:** Support for ngrok tunnels, providing an alternative for secure public access.
*   **Multi-File and Directory Sharing:** Capability to share individual files, batches, or entire directories.
*   **Two-Way Sharing:** Supports both sending files from the computer and receiving uploads from mobile devices.

## Installation

### System Requirements

| Requirement | Minimum |
| :--- | :--- |
| Python | 3.8+ |
| OS | Linux, macOS, Windows |
| `ssh` binary | Required for SSH mode on Linux/macOS |
| ngrok | Required for ngrok mode |

```bash
pip install qrtunnel
```

## Usage

### 1. Interactive TUI (Default)
Running `qrtunnel` without arguments launches the interactive interface.

```bash
qrtunnel
```

#### TUI Navigation
*   **Up/Down Arrows:** Move the selection cursor.
*   **Enter / Right Arrow:** Confirm selection or proceed to the next screen.
*   **Left Arrow:** Return to the previous screen.
*   **Space / Enter:** Toggle file selection in the file picker.
*   **Forward Slash ( / ):** Enter search mode within the file picker to filter files by name.
*   **Escape (ESC):** Cancel search mode.
*   **Q / Ctrl+C:** Exit the application.

### 2. Command Line Interface (CLI)
The CLI supports subcommands for direct execution and scripting.

#### Sending Files
```bash
# General syntax
qrtunnel send <path1> <path2> ... [options]

# Example: Share a file and a folder using a specific port
qrtunnel send report.pdf data/ -8080

# Example: Force LAN-only mode
qrtunnel send images/ -lan
```

#### Receiving Files
```bash
# Receive files into the current directory
qrtunnel receive

# Receive files into a specific directory using ngrok
qrtunnel receive ./uploads -ngrok
```

#### Transfer History
```bash
qrtunnel history
qrtunnel history --limit 5
```

### Tunneling Options

| Option | Description |
| :--- | :--- |
| `-smart` | (Default) Enables both LAN and Public Tunnel with auto-detection. |
| `-lan` | LAN only. Fastest transfer, accessible only on the same Wi-Fi. |
| `-ssh` | Public link via localhost.run. No account required. |
| `-cloudflare` | Public link via Cloudflare Tunnel. Requires `cloudflared`. |
| `-ngrok` | Public link via ngrok. Requires an authtoken. |

### Configuration and Ports
*   **Configuration and Ports:** The tool defaults to a random port between 20000 and 60000. Users can specify a port using `-p <port>` or the shorthand `-<port>` (e.g., `-9000`).

## Limitations

*   `localhost.run` may enforce rate limits or session duration limits.
*   ngrok free-tier accounts may have tunnel, bandwidth, or session limits.
*   Anyone with the active transfer URL and LAN passcode can access the session.
*   The LAN OTP is valid for the full session and is not invalidated after first use.
*   qrtunnel is intended for convenience sharing, not sensitive or regulated data.

## Security

qrtunnel is designed for short-lived convenience transfers between devices you control. LAN access is protected by a randomized 6-digit OTP, and the server listens on a selected local port for the current session.

Public tunnel URLs are bearer links: anyone who receives the active URL can reach the transfer page while the session is running. Traffic that uses third-party tunnel providers is subject to those providers' transport, logging, and account policies.

## License
MIT
