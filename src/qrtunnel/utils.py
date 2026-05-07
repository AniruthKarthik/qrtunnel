"""General network and formatting helpers."""

import ipaddress
import platform
import socket


# ─────────────────────────────────────────────────────────
#  HELPERS  (preserved from original)
# ─────────────────────────────────────────────────────────
def format_size(b):
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} TB"


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        addr = ipaddress.ip_address(ip)
        if addr.is_private and not addr.is_loopback:
            return str(ip)
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            addr = ipaddress.ip_address(ip)
            if addr.is_private and not addr.is_loopback:
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


