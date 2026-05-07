# QRTunnel — Pre-filed Issues Reference

Copy each block below to create issues on GitHub. Labels are listed at the top of each issue.

---

## BUGS

---

### Issue: LAN OTP never invalidated after first use

**Labels:** `bug`, `security`

**Description:**

The 6-digit OTP for LAN mode is static for the entire session. Any device that obtains the passcode can continue accessing the server indefinitely during the session.

**Expected behavior:** Optionally invalidate OTP after first successful use, or at minimum document this limitation clearly in the UI and README.

---

## FEATURES / ENHANCEMENTS

---

### Issue: Performance optimization of existing tunnel backends (SSH & ngrok) #20

**Labels:** `enhancement`, `performance`

**Description:**

Currently, the SSH and ngrok backends use default configurations. Investigate and implement performance optimizations (e.g., SSH multiplexing, compressed streams, or optimized ngrok regions) to reduce latency and increase throughput for public links.

---

### Issue: Implement direct connection mode using UPnP/NAT-PMP #21

**Labels:** `enhancement`, `network`

**Description:**

To avoid third-party tunnel latency and limits, implement automatic port forwarding via UPnP or NAT-PMP. This would allow a direct public connection to the host machine when the router supports it.

---
