# QRTunnel

Cross-platform file sharing via SSH reverse tunneling and QR codes. Allows sharing files with mobile devices anywhere in the world, even behind NAT/firewalls.

Now featuring a **new interactive Terminal User Interface (TUI)** for easier navigation!

## Features

*   **Interactive TUI:** A beautiful, easy-to-use terminal interface to select files, choose modes, and configure ports using arrow keys.
*   **Simple File Sharing:** Share one or more files directly from your command line.
*   **Receive Files:** Start in upload mode to receive files from any device with a web browser.
*   **Smart Mode:** Automatically provides both a global Internet link and a high-speed LAN link. The client device auto-detects if it's on the same Wi-Fi and switches to maximum speed.
*   **High-Speed LAN Sharing:** Use the `--lan` flag (or select LAN in TUI) to share files directly over your local network, keeping data private and fast.
*   **LAN Security (OTP):** High-speed LAN transfers are protected by a random 6-digit passcode displayed only on your terminal.
*   **Randomized & Custom Ports:** Defaults to a random port (20000-60000) for security, or choose your own custom port.
*   **Secure Tunnels:** Supports both **SSH Tunneling** (default on Linux/macOS) and **ngrok** (default on Windows) for secure, public access.
    *   **SSH Tunneling:** Uses `localhost.run` for instant tunneling without any account or sign-up.
    *   **Ngrok Support:** Reliable tunneling via ngrok (requires free account).
*   **QR Code Display:** Generates a scannable QR code in your terminal for easy access on mobile devices.
*   **Web Interface:** Provides a simple web page for recipients to download shared files or upload files to you.

## Installation

```bash
pip install qrtunnel
```

This will install `qrtunnel` and all its dependencies.

## Usage

### 1. Interactive Mode (TUI)

Simply run `qrtunnel` without any arguments to launch the interactive interface:

```bash
qrtunnel
```

Use your **Arrow Keys** to:
1.  Select **SEND** or **RECEIVE**.
2.  Navigate and select files (Space to toggle, Enter to confirm).
3.  Choose your Tunnel Mode (Smart, LAN, SSH, Ngrok).
4.  Select a Port (Random or Custom).
5.  **Launch!**

### 2. Command Line Interface (CLI)

For quick, scripted, or direct usage, use the `send` and `receive` subcommands.

#### Sharing Files (Send)

To share one or more files:

```bash
qrtunnel send <file_path1> [<file_path2> ...]
```

Example:
```bash
qrtunnel send mydocument.pdf photos/
```

**Options:**
*   `-smart`: (Default) Enables both LAN and Internet links.
*   `-lan`: Force LAN-only mode (fastest, same Wi-Fi only).
*   `-ssh`: Force SSH tunneling (no account needed).
*   `-ngrok`: Force ngrok tunneling (requires account).
*   `-p <port>` or `-<port>`: Specify a custom port (e.g., `-p 8080` or `-8080`).

#### Receiving Files (Receive)

To receive files on your computer:

```bash
qrtunnel receive [destination_directory]
```

Example:
```bash
qrtunnel receive ./downloads
```

This starts the server in upload mode. Scan the QR code to get a web page where you can upload files to your computer.

### Tunnel Modes Explained

*   **Smart Mode:** Best for most cases. It creates a public tunnel AND a local LAN server. The phone will try to use the LAN connection first (fastest) and fall back to the tunnel if needed.
*   **LAN Mode:** Only accessible to devices on the same Wi-Fi. Fastest speed, maximum privacy.
*   **SSH Mode:** (Linux/macOS Default) Uses `localhost.run` to create a public link. No account required.
*   **Ngrok Mode:** (Windows Default) Uses `ngrok` for a stable public link. Requires a free ngrok account.

### Ngrok Setup

If you use ngrok (default on Windows, optional on Linux/macOS), you'll need to set up your authtoken once. The TUI or CLI will prompt you if it's missing, or you can configure it manually if needed.

## License

MIT