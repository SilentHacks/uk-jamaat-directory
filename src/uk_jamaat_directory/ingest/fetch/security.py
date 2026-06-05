from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_fetch_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "unsupported URL scheme"
    if not parsed.hostname:
        return "missing hostname"

    hostname = parsed.hostname.lower()
    if hostname in _BLOCKED_HOSTNAMES:
        return "blocked hostname"

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return None

    if _is_blocked_ip(str(ip)):
        return "blocked host address"
    return None


async def ensure_resolvable_public_host(url: str) -> str | None:
    blocked = validate_fetch_url(url)
    if blocked:
        return blocked

    hostname = urlparse(url).hostname
    if hostname is None:
        return "missing hostname"

    def _resolve() -> list[str]:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        return [info[4][0] for info in infos]

    try:
        addresses = await asyncio.to_thread(_resolve)
    except socket.gaierror:
        return f"cannot resolve host: {hostname}"

    for address in addresses:
        if _is_blocked_ip(address):
            return "blocked host address"
    return None
