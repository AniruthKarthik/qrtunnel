# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.5.x   | ✅ Yes     |
| < 3.5   | ❌ No      |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately by emailing the maintainer (see GitHub profile) or via [GitHub's private vulnerability reporting](https://github.com/AniruthKarthik/qrtunnel/security/advisories/new).

Include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

You will receive acknowledgment within 72 hours. If the vulnerability is confirmed, a patch will be released and you will be credited in the release notes unless you request otherwise.

## Security Model

QRTunnel's security is intentionally minimal. Understand the limitations:

- **LAN OTP** is a 6-digit passcode. It is single-use per session, not per download.
- **SSH tunnel via `localhost.run`** is an unauthenticated third-party service. Traffic passes through their servers.
- **ngrok** is a third-party service. Traffic passes through ngrok's infrastructure.
- **No TLS verification** is performed on tunnel connections beyond what the tunnel provider offers.
- **No authentication** is required to download files once the QR URL is known by any device.

QRTunnel is designed for quick, low-stakes transfers. It is **not** suitable for transferring sensitive, private, or regulated data.
