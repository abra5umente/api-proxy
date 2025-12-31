# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

API Proxy service that routes requests through a residential IP for APIs that block cloud/datacenter IPs (e.g., Reddit). Built with FastAPI and httpx.

**Request flow:** Claude Container → Cloudflare Tunnel → This Proxy → Target API

## Development Commands

```bash
# Run locally
uvicorn app:app --host 0.0.0.0 --port 8000

# Run with auto-reload during development
uvicorn app:app --reload --port 8000

# Build Docker image
docker build -t api-proxy .

# Run Docker container
docker run -p 8000:8000 -e PROXY_AUTH_TOKEN=your-token api-proxy
```

## Architecture

Single-file FastAPI application (`app.py`) with two endpoints:

- `GET /health` - Unauthenticated health check
- `POST /proxy` - Authenticated proxy endpoint (requires `X-Proxy-Token` header)

**Environment variables:**
- `PROXY_AUTH_TOKEN` (required) - Auth token for `/proxy` requests
- `ALLOWED_DOMAINS` - Comma-separated domain whitelist (empty = allow all)
- `PROXY_TIMEOUT` - Request timeout in seconds (default: 30)

**Domain validation:** `is_domain_allowed()` checks against whitelist, supports subdomains (e.g., `reddit.com` allows `oauth.reddit.com`).
