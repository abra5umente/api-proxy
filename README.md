# API Proxy for Claude Skills

Routes API requests through your residential IP for services that block cloud/datacenter IPs (like Reddit, some game APIs, etc).

## Why?

Claude's container runs from cloud infrastructure. Some APIs (notably Reddit) block requests from known cloud IP ranges. This proxy lets Claude's skills route requests through your home network instead.

```
Claude Container → Your Cloudflare Tunnel → This Proxy → Target API
     (blocked)                                              (allowed!)
```

## Quick Start

### 1. Build and deploy

```bash
docker build -t your-registry/api-proxy:latest .
docker push your-registry/api-proxy:latest
```

### 2. Add to Docker Compose

```yaml
services:
  api-proxy:
    image: your-registry/api-proxy:latest
    container_name: api-proxy
    restart: unless-stopped
    environment:
      - PROXY_AUTH_TOKEN=your-secure-token-here
      - ALLOWED_DOMAINS=reddit.com,www.reddit.com,oauth.reddit.com
      - PROXY_TIMEOUT=30
    networks:
      - your-network
```

### 3. Expose via Cloudflare Tunnel

Add a route in your `config.yml` or Zero Trust dashboard:

```yaml
- hostname: proxy.yourdomain.com
  service: http://api-proxy:8000
```

### 4. Whitelist in Claude

Add `proxy.yourdomain.com` to your Claude allowed domains in Settings.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROXY_AUTH_TOKEN` | Yes | `changeme` | Auth token for requests |
| `ALLOWED_DOMAINS` | No | *(all)* | Comma-separated domain whitelist |
| `PROXY_TIMEOUT` | No | `30` | Request timeout in seconds |

## API Reference

### `GET /health`
Health check endpoint. No authentication required.

```bash
curl https://proxy.yourdomain.com/health
# {"status": "ok"}
```

### `POST /proxy`
Proxy a request through residential IP. Requires `X-Proxy-Token` header.

**Request body:**
```json
{
  "url": "https://api.example.com/endpoint",
  "method": "GET",
  "headers": {"User-Agent": "MyBot/1.0"},
  "body": "{\"optional\": \"request body\"}"
}
```

**Response:**
```json
{
  "status_code": 200,
  "headers": {"content-type": "application/json", ...},
  "body": "{\"response\": \"from target API\"}"
}
```

---

## Claude Skills Integration

This proxy is designed to work with Claude's [Skills system](https://docs.anthropic.com/). Here's how to integrate it.

### Option 1: Create a Reusable Proxy Helper

Create a `proxy_helper.py` that your skills can import:

```python
"""
proxy_helper.py - Copy this to your skill's scripts/ folder
"""
import urllib.request
import json

PROXY_URL = "https://proxy.yourdomain.com/proxy"
PROXY_TOKEN = "your-token-here"
DEFAULT_USER_AGENT = "Claude-Skill/1.0"

def proxy_request(url: str, method: str = "GET", headers: dict = None, body: str = None) -> dict:
    """Make a request through the residential proxy."""
    req_headers = headers or {}
    if "User-Agent" not in req_headers:
        req_headers["User-Agent"] = DEFAULT_USER_AGENT
    
    payload = {"url": url, "method": method, "headers": req_headers}
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
        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode())
        
        if result["status_code"] >= 400:
            return {"error": f"Target returned {result['status_code']}"}
        
        return json.loads(result["body"])
    except Exception as e:
        return {"error": str(e)}

def proxy_get(url: str, headers: dict = None) -> dict:
    """Convenience wrapper for GET requests."""
    return proxy_request(url, method="GET", headers=headers)

def proxy_post(url: str, body: str, headers: dict = None) -> dict:
    """Convenience wrapper for POST requests."""
    return proxy_request(url, method="POST", headers=headers, body=body)
```

### Option 2: Create an api-proxy Skill

Bundle the helper as a standalone skill that other skills can reference:

```
api-proxy/
├── SKILL.md
└── scripts/
    └── proxy_helper.py
```

**SKILL.md:**
```markdown
---
name: api-proxy
description: Routes API requests through residential proxy for APIs that block cloud IPs.
---

# API Proxy Skill

Copy `scripts/proxy_helper.py` to your skill's scripts folder, then:

\`\`\`python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proxy_helper import proxy_get

data = proxy_get("https://www.reddit.com/r/homelab.json")
\`\`\`
```

### Using in Your Skills

Once you have the proxy helper, use it in your skill scripts:

```python
#!/usr/bin/env python3
"""browse_subreddit.py - Example skill script"""
import sys
import os
import json

# Import the proxy helper
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proxy_helper import proxy_get

def browse_subreddit(subreddit: str, limit: int = 10) -> dict:
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    return proxy_get(url)

if __name__ == "__main__":
    subreddit = sys.argv[1] if len(sys.argv) > 1 else "homelab"
    result = browse_subreddit(subreddit)
    print(json.dumps(result, indent=2))
```

### Skill Structure Example

A complete Reddit skill using the proxy:

```
reddit/
├── SKILL.md
└── scripts/
    ├── proxy_helper.py      # Copied from api-proxy skill
    ├── browse_subreddit.py
    ├── search_reddit.py
    └── get_post_details.py
```

---

## Security

- **Auth token**: Required for all `/proxy` requests. Generate with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- **Domain whitelist**: Restrict which APIs can be proxied
- **No direct exposure**: Only accessible via Cloudflare Tunnel
- **No host port binding**: Container doesn't expose ports to host network

### Token Storage

Your token lives in:
1. Container environment variables (not publicly visible)
2. Your skill files (in Claude's private `/mnt/skills/user/` directory)

**Don't commit tokens to public repos!** Use `.gitignore` or environment variable substitution.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| 401 from proxy | Invalid token | Check `X-Proxy-Token` matches `PROXY_AUTH_TOKEN` |
| 403 from proxy | Domain not whitelisted | Add domain to `ALLOWED_DOMAINS` |
| 503 from proxy | Rate limited / upstream error | Retry after delay |
| 504 from proxy | Timeout | Increase `PROXY_TIMEOUT` |
| Connection refused | Proxy not running | Check container status and CF tunnel |

## License

MIT
