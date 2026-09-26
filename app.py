"""
API Proxy Service
Routes requests through residential IP for APIs that block cloud IPs.
"""

import asyncio
import ipaddress
import os
import secrets
import socket
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

# Config from environment
AUTH_TOKEN = os.getenv("PROXY_AUTH_TOKEN", "")
if not AUTH_TOKEN:
    raise RuntimeError("PROXY_AUTH_TOKEN must be set")

ALLOWED_DOMAINS = [
    d.strip().lower().rstrip(".")
    for d in os.getenv("ALLOWED_DOMAINS", "").split(",")
    if d.strip()
]
TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "30"))

BLOCKED_HOSTS = {
    "metadata.google.internal",  # GCP metadata
    "metadata",                  # Azure metadata shortname
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # trust_env=False: this service *is* the egress, so ignore any HTTP(S)_PROXY
    # env vars, which would also defeat the DNS pinning below.
    app.state.client = httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=False, trust_env=False
    )
    yield
    await app.state.client.aclose()


app = FastAPI(title="API Proxy", docs_url=None, redoc_url=None, lifespan=lifespan)


class ProxyRequest(BaseModel):
    url: str
    method: str = "GET"
    headers: Optional[dict] = None
    body: Optional[str] = None


def get_hostname(url: str) -> str:
    """Extract the bare hostname (no userinfo, port or IPv6 brackets)."""
    return (urlparse(url).hostname or "").rstrip(".")


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that isn't a public unicast address."""
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


async def resolve_host(host: str) -> list[str]:
    """Resolve a hostname to all of its IP addresses."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


async def validate_url(url: str) -> tuple[bool, str, Optional[str]]:
    """
    Validate URL for SSRF protection.
    Returns (is_valid, error_message, pinned_ip). The caller must connect to
    pinned_ip so a second DNS lookup can't be rebound to an internal address.
    """
    parsed = urlparse(url)

    # 1. Scheme validation
    if parsed.scheme not in ("http", "https"):
        return False, f"Scheme '{parsed.scheme}' not allowed. Use http or https.", None

    # 2. Extract host
    try:
        parsed.port  # raises on a malformed port
    except ValueError:
        return False, "Invalid port", None
    host = get_hostname(url)
    if not host:
        return False, "Missing host", None

    # 3. Block metadata endpoints by name
    if host in BLOCKED_HOSTS:
        return False, "Metadata endpoints are blocked", None

    # 4. Literal IP: check it directly
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if is_blocked_ip(ip):
            return False, "Private/internal IP addresses are blocked", None
        return True, "", host

    # 5. Hostname: every resolved address must be public
    try:
        addrs = await resolve_host(host)
    except socket.gaierror:
        return False, "Could not resolve host", None
    if not addrs:
        return False, "Could not resolve host", None
    for addr in addrs:
        if is_blocked_ip(ipaddress.ip_address(addr)):
            return False, "Hostname resolves to private/internal IP", None

    return True, "", addrs[0]


def is_domain_allowed(url: str) -> bool:
    """Check if URL domain is in allowlist (if configured)."""
    if not ALLOWED_DOMAINS:
        return True  # No whitelist = allow all

    domain = get_hostname(url)
    for allowed in ALLOWED_DOMAINS:
        if domain == allowed or domain.endswith(f".{allowed}"):
            return True
    return False


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/proxy")
async def proxy(
    request: ProxyRequest,
    x_proxy_token: str = Header(..., alias="X-Proxy-Token")
):
    # Validate auth token (constant-time)
    if not secrets.compare_digest(x_proxy_token.encode(), AUTH_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check domain whitelist
    if not is_domain_allowed(request.url):
        raise HTTPException(status_code=403, detail="Domain not allowed")

    # SSRF protection
    is_valid, error, pinned_ip = await validate_url(request.url)
    if not is_valid:
        raise HTTPException(status_code=403, detail=error)

    # Connect to the validated IP, but keep the original Host header and TLS
    # SNI/cert hostname so the upstream sees a normal request.
    try:
        original = httpx.URL(request.url)
    except httpx.InvalidURL as e:
        raise HTTPException(status_code=400, detail=f"Invalid URL: {e}")
    pinned_url = original.copy_with(host=pinned_ip)

    req_headers = {k: v for k, v in (request.headers or {}).items() if k.lower() != "host"}
    host_header = original.host if ":" not in original.host else f"[{original.host}]"
    if original.port is not None:
        host_header += f":{original.port}"
    req_headers["Host"] = host_header

    client: httpx.AsyncClient = app.state.client
    try:
        response = await client.request(
            method=request.method.upper(),
            url=pinned_url,
            headers=req_headers,
            content=request.body if request.body else None,
            extensions={"sni_hostname": original.host},
        )

        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response.text
        }

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream timeout")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")
