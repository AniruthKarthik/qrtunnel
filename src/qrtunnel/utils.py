"""General network and formatting helpers."""

import ipaddress
import platform
import random
import socket
import subprocess

IGNORED_INTERFACE_PREFIXES = (
    "br-",
    "docker",
    "lo",
    "tap",
    "tun",
    "veth",
    "virbr",
    "vmnet",
    "wg",
)


# ─────────────────────────────────────────────────────────
#  HELPERS  (preserved from original)
# ─────────────────────────────────────────────────────────
def format_size(b):
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} TB"


def is_port_available(port, host="0.0.0.0"):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
    except OSError:
        return False
    return True


def find_available_port(start=20000, end=60000, attempts=100):
    for _ in range(attempts):
        port = random.randint(start, end)
        if is_port_available(port):
            return port
    raise OSError(f"No available port found after {attempts} attempts")


def _is_usable_lan_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private and not addr.is_loopback and not addr.is_link_local


def _is_ignored_interface(name):
    normalized = name.lower().split("@", 1)[0]
    return normalized.startswith(IGNORED_INTERFACE_PREFIXES)


def _get_linux_interface_ips():
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", "scope", "global"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return []

    ips = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4 or _is_ignored_interface(parts[1]):
            continue
        try:
            inet_index = parts.index("inet")
        except ValueError:
            continue
        ip = parts[inet_index + 1].split("/", 1)[0]
        if _is_usable_lan_ip(ip):
            ips.append(ip)
    return ips


def get_lan_ip():
    if platform.system() == "Linux":
        interface_ips = _get_linux_interface_ips()
        if interface_ips:
            return interface_ips[0]

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if _is_usable_lan_ip(ip):
                return str(ip)
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if _is_usable_lan_ip(ip):
            return str(ip)
    except Exception:
        pass
    return None


def is_same_lan(client_ip, server_ip):
    try:
        c_ip = ipaddress.ip_address(client_ip)
        s_ip = ipaddress.ip_address(server_ip)
        if not (c_ip.is_private and s_ip.is_private):
            return False
        if c_ip == s_ip:
            return True
        if platform.system() == "Linux":
            try:
                with open("/proc/net/arp") as f:
                    if client_ip in f.read():
                        return True
            except Exception:
                pass
        c_net = ipaddress.ip_network(f"{client_ip}/24", strict=False)
        return s_ip in c_net
    except Exception:
        return False
