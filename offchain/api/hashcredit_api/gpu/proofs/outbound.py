"""
SSRF defence for any outbound HTTP the API may perform on behalf of a proof query.

No endpoint accepts a URL. Outbound targets are allowed only when the host is one of the manifest
`proofService` hosts, the scheme is https, and the host is not a literal private/loopback/link-local
address. Redirects are not followed (a redirect to another host is rejected by construction).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def _is_private_literal(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host in {"localhost", "localhost.localdomain"} or host.endswith(".local")
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_allowed_outbound(url: str, allowed_hosts: frozenset[str] | set[str], *, allow_http: bool = False) -> bool:
    try:
        p = urlsplit(url)
    except Exception:
        return False
    if p.scheme != "https" and not (allow_http and p.scheme == "http"):
        return False
    if p.username or p.password:
        return False
    host = (p.hostname or "").lower()
    if not host or _is_private_literal(host):
        return False
    return host in {h.lower() for h in allowed_hosts}
