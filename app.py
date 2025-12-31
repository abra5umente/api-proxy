"""
API Proxy Service
Routes requests through residential IP for APIs that block cloud IPs.
"""

import os
import socket
import ipaddress
import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="API Proxy", docs_url=None, redoc_url=None)

# Config from environment
AUTH_TOKEN = os.getenv("PROXY_AUTH_TOKEN", "changeme")
ALLOWED_DOMAINS = os.getenv("ALLOWED_DOMAINS", "").split(",") if os.getenv("ALLOWED_DOMAINS") else []
TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "30"))


class ProxyRequest(BaseModel):
    url: str
    method: str = "GET"
    headers: Optional[dict] = None
    body: Optional[str] = None


def validate_url(url: str) -> tuple[bool, str]:
    """
    Validate URL for SSRF protection.
    Returns (is_valid, error_message).
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)

    # 1. Scheme validation
    if parsed.scheme not in ("http", "https"):
        return False, f"Scheme '{parsed.scheme}' not allowed. Use http or https."

    # 2. Extract host (strip port if present)
    host = parsed.netloc.split(":")[0].lower()

    # 3. Block metadata endpoints
    BLOCKED_HOSTS = {
        "169.254.169.254",          # AWS/GCP/Azure metadata
        "metadata.google.internal", # GCP metadata
        "metadata",                 # Azure metadata shortname
    }
    if host in BLOCKED_HOSTS:
        return False, "Metadata endpoints are blocked"

    # 4. Check if host is an IP address and block private ranges
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, "Private/internal IP addresses are blocked"
    except ValueError:
        # Not an IP address, it's a hostname - resolve it
        try:
            resolved_ip = socket.gethostbyname(host)
            ip = ipaddress.ip_address(resolved_ip)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "Hostname resolves to private/internal IP"
        except socket.gaierror:
            pass  # DNS resolution failed, let httpx handle it

    return True, ""


def is_domain_allowed(url: str) -> bool:
    """Check if URL domain is in allowlist (if configured)."""
    if not ALLOWED_DOMAINS or ALLOWED_DOMAINS == [""]:
        return True  # No whitelist = allow all
    
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower()
    
    for allowed in ALLOWED_DOMAINS:
        allowed = allowed.strip().lower()
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
    # Validate auth token
    if x_proxy_token != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Check domain whitelist
    if not is_domain_allowed(request.url):
        raise HTTPException(status_code=403, detail=f"Domain not allowed")

    # SSRF protection
    is_valid, error = validate_url(request.url)
    if not is_valid:
        raise HTTPException(status_code=403, detail=error)

    # Build request
    req_headers = request.headers or {}
    
    # Make the proxied request
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        try:
            response = await client.request(
                method=request.method.upper(),
                url=request.url,
                headers=req_headers,
                content=request.body if request.body else None
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
