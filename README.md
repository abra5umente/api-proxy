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

This proxy is designed to work with Claude's [Skills system](https://docs.anthropic.com/). A ready-to-use skill is included in the `skill/` directory:

```
skill/
├── skill.md          # Skill definition
├── proxy_helper.py   # Reusable helper module
└── fetch.py          # Ad-hoc fetch script
```

### Quick Start

**Ad-hoc requests** (when direct fetch fails with 403):
```bash
python3 skill/fetch.py "https://api.example.com/endpoint"
python3 skill/fetch.py "https://api.example.com/endpoint" POST '{"key": "value"}'
```

**Building new skills**: Copy `skill/proxy_helper.py` into your skill's `scripts/` folder, then:
```python
from proxy_helper import proxy_get, proxy_request

data = proxy_get("https://api.example.com/endpoint")
```

See `skill/skill.md` for full documentation.

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
