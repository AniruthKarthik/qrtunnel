"""General network and formatting helpers."""

import hashlib
import ipaddress
import platform
import random
import socket
import subprocess
import threading
from pathlib import Path

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


def format_progress(transferred, total, width=24):
    if total <= 0:
        return f"{format_size(transferred)} transferred"
    ratio = min(max(transferred / total, 0), 1)
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {ratio * 100:5.1f}% {format_size(transferred)} / {format_size(total)}"


_CHECKSUM_CACHE = {}
_CHECKSUM_LOCK = threading.Lock()


def store_cached_checksum(path, hexdigest):
    """Store precomputed checksum (e.g. from upload streaming) to avoid redundant disk reads."""
    try:
        p = Path(path)
        stat = p.stat()
        cache_key = (str(p.resolve()), stat.st_mtime_ns, stat.st_size)
        with _CHECKSUM_LOCK:
            if len(_CHECKSUM_CACHE) > 2048:
                _CHECKSUM_CACHE.clear()
            _CHECKSUM_CACHE[cache_key] = hexdigest
    except Exception:
        pass


def sha256_file(path, chunk_size=1024 * 1024, use_cache=True):
    cache_key = None
    if use_cache:
        try:
            p = Path(path)
            stat = p.stat()
            cache_key = (str(p.resolve()), stat.st_mtime_ns, stat.st_size)
            with _CHECKSUM_LOCK:
                if cache_key in _CHECKSUM_CACHE:
                    return _CHECKSUM_CACHE[cache_key]
        except Exception:
            cache_key = None

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    hexdigest = digest.hexdigest()

    if use_cache and cache_key:
        with _CHECKSUM_LOCK:
            if len(_CHECKSUM_CACHE) > 2048:
                _CHECKSUM_CACHE.clear()
            _CHECKSUM_CACHE[cache_key] = hexdigest

    return hexdigest


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


def _get_darwin_interface_ips():
    ips = []
    for iface in ("en0", "en1", "en2", "en3", "en4"):
        try:
            result = subprocess.run(
                ["ipconfig", "getifaddr", iface],
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
            ip = result.stdout.strip()
            if ip and _is_usable_lan_ip(ip):
                ips.append(ip)
        except Exception:
            pass
    return ips


def get_lan_ip():
    if platform.system() == "Linux":
        interface_ips = _get_linux_interface_ips()
        if interface_ips:
            return interface_ips[0]

    if platform.system() == "Darwin":
        interface_ips = _get_darwin_interface_ips()
        if interface_ips:
            return interface_ips[0]

    # Fast UDP routing table probe: kernel resolves local interface IP in <0.1ms without DNS
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if _is_usable_lan_ip(ip):
            return str(ip)
    except Exception:
        pass

    # Fallback to hostname resolution if UDP routing probe is unavailable (e.g. offline)
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
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


_CACHED_PUBLIC_IP = None


def get_public_ip(timeout=2.0):
    """Fetch the host's public WAN IP for same-network matching."""
    global _CACHED_PUBLIC_IP
    if _CACHED_PUBLIC_IP:
        return _CACHED_PUBLIC_IP
    try:
        import urllib.request

        req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "qrtunnel"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ip = resp.read().decode("utf-8").strip()
            if ip:
                _CACHED_PUBLIC_IP = ip
                return _CACHED_PUBLIC_IP
    except Exception:
        pass
    return None


def get_host_ipv6_subnets():
    """Retrieve all global IPv6 /64 subnets configured on the host's interfaces."""
    subnets = []
    try:
        hostname = socket.gethostname()
        for res in socket.getaddrinfo(hostname, None, socket.AF_INET6):
            ip_str = res[4][0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_global and not ip.is_link_local:
                net = ipaddress.ip_network(f"{ip_str}/64", strict=False)
                if net not in subnets:
                    subnets.append(net)
    except Exception:
        pass
    return subnets


def is_same_network(client_ip, server_lan_ip=None):
    """Determine whether client_ip belongs to the same local network or Wi-Fi as the host."""
    if not client_ip or client_ip in ("127.0.0.1", "::1"):
        return False

    try:
        c_ip = ipaddress.ip_address(client_ip)
    except Exception:
        return False

    # Check direct LAN if private IP
    if c_ip.is_private:
        if server_lan_ip and is_same_lan(client_ip, server_lan_ip):
            return True

    # Check IPv6 global prefix matching (/64)
    if c_ip.version == 6:
        for subnet in get_host_ipv6_subnets():
            try:
                if c_ip in subnet:
                    return True
            except Exception:
                pass

    # Check Public IPv4 WAN matching
    public_ip = get_public_ip()
    if public_ip:
        try:
            p_ip = ipaddress.ip_address(public_ip)
            if c_ip == p_ip:
                return True
        except Exception:
            pass

    return False
