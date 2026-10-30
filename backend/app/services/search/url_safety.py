"""SSRF-safe URL validation and fetching."""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/pdf")
MAX_REDIRECTS = 4
MAX_BYTES = 3 * 1024 * 1024
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid", "spm"}
BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata", "instance-data"}


class UnsafeURLError(ValueError):
    pass


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    if scheme == "http":
        scheme = "https"
    host = (parts.hostname or "").lower().removeprefix("www.")
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = parts.path.rstrip("/") or ""
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
        )
    )
    return urlunsplit((scheme, f"{host}{port}", path, query, ""))


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def check_url_syntax(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError("only http and https URLs are allowed")
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with credentials are not allowed")
    if host in BLOCKED_HOSTNAMES or host.endswith((".localhost", ".internal", ".local")):
        raise UnsafeURLError("host is not allowed")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeURLError("invalid port") from exc
    return host, port


async def resolve_and_check(url: str) -> None:
    """Raise UnsafeURLError unless every resolved address of the host is public."""
    host, port = check_url_syntax(url)
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public_ip(literal):
            raise UnsafeURLError("address is private or reserved")
        return
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=5)
    except (OSError, TimeoutError) as exc:
        raise UnsafeURLError("host could not be resolved") from exc
    if not infos:
        raise UnsafeURLError("host could not be resolved")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not is_public_ip(ip):
            raise UnsafeURLError("host resolves to a private or reserved address")


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    body: bytes


def check_peer(response: httpx.Response) -> None:
    """Re-check the address the socket actually connected to.

    resolve_and_check() runs before the request, and DNS can answer differently a moment later
    (DNS rebinding). Checking the connected peer stops a private address's response from being read.
    Transports without a network stream (test mocks) are skipped.
    """
    stream = response.extensions.get("network_stream")
    addr = stream.get_extra_info("server_addr") if stream is not None else None
    if not addr:
        return
    try:
        ip = ipaddress.ip_address(addr[0].split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeURLError("could not verify connected address") from exc
    if not is_public_ip(ip):
        raise UnsafeURLError("connected to a non-public address")


async def safe_fetch(url: str, *, client: httpx.AsyncClient, timeout: float = 15.0) -> FetchResult:
    """GET with manual redirects; every hop is re-validated. Caps size and content type."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        await resolve_and_check(current)
        async with client.stream(
            "GET",
            current,
            follow_redirects=False,
            timeout=timeout,
            headers={"User-Agent": "ArvenAI-Research/1.0 (+local research assistant)", "Accept": "text/html,text/plain,application/pdf"},
        ) as response:
            check_peer(response)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise UnsafeURLError("redirect without location")
                current = urljoin(current, location)
                continue
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if response.status_code >= 400:
                return FetchResult(current, response.status_code, content_type, b"")
            if content_type and not content_type.startswith(ALLOWED_CONTENT_TYPES):
                raise UnsafeURLError(f"unsupported content type {content_type}")
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                raise UnsafeURLError("response too large")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UnsafeURLError("response too large")
                chunks.append(chunk)
            return FetchResult(current, response.status_code, content_type, b"".join(chunks))
    raise UnsafeURLError("too many redirects")
