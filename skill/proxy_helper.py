"""
Proxy helper for API calls through residential proxy.
Copy this file to your skill's scripts/ folder.

Usage:
    from proxy_helper import proxy_get, proxy_request
    
    # Simple GET
    data = proxy_get("https://api.example.com/endpoint")
    
    # Full control
    data = proxy_request(
        url="https://api.example.com/endpoint",
        method="POST",
        headers={"Authorization": "Bearer xyz"},
        body='{"key": "value"}'
    )
"""

import urllib.request
import json

PROXY_URL = "https://proxy.url.here"
PROXY_TOKEN = "proxy_token_here"
DEFAULT_USER_AGENT = "Claude-Skill/1.0"
DEFAULT_TIMEOUT = 30


def proxy_request(url: str, method: str = "GET", headers: dict = None, body: str = None) -> dict:
    """
    Make a request through the residential proxy.
    
    Args:
        url: Target URL to request
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        headers: Optional dict of headers to send to target
        body: Optional request body (string)
    
    Returns:
        Parsed JSON response, or {"error": "message"} on failure
    """
    req_headers = headers or {}
    if "User-Agent" not in req_headers:
        req_headers["User-Agent"] = DEFAULT_USER_AGENT
    
    payload = {
        "url": url,
        "method": method,
        "headers": req_headers
    }
    
    if body:
        payload["body"] = body
    
    req = urllib.request.Request(
        PROXY_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Proxy-Token": PROXY_TOKEN
        }
    )
    
    try:
        response = urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT)
        result = json.loads(response.read().decode())
        
        if result["status_code"] >= 400:
            return {"error": f"Target returned {result['status_code']}", "status_code": result["status_code"]}
        
        # Try to parse body as JSON, fall back to raw text
        try:
            return json.loads(result["body"])
        except json.JSONDecodeError:
            return {
                "raw_body": result["body"], 
                "status_code": result["status_code"],
                "headers": result.get("headers", {})
            }
    
    except urllib.error.HTTPError as e:
        return {"error": f"Proxy error: {e.code}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection error: {e.reason}"}
    except json.JSONDecodeError:
        return {"error": "Failed to parse proxy response"}


def proxy_get(url: str, headers: dict = None) -> dict:
    """Convenience wrapper for GET requests."""
    return proxy_request(url, method="GET", headers=headers)


def proxy_post(url: str, body: str, headers: dict = None) -> dict:
    """Convenience wrapper for POST requests."""
    return proxy_request(url, method="POST", headers=headers, body=body)