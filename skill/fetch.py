#!/usr/bin/env python3
"""
Ad-hoc fetch through residential proxy.

Use when a direct curl/fetch fails due to IP blocking.

Usage:
    python3 fetch.py <url> [method] [body]

Examples:
    # Simple GET
    python3 fetch.py "https://api.reddit.com/r/ClaudeAI/hot"
    
    # POST with body
    python3 fetch.py "https://api.example.com/endpoint" POST '{"key": "value"}'
"""

import sys
import os
import json

# Import from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proxy_helper import proxy_request

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fetch.py <url> [method] [body]"}))
        sys.exit(1)
    
    url = sys.argv[1]
    method = sys.argv[2] if len(sys.argv) > 2 else "GET"
    body = sys.argv[3] if len(sys.argv) > 3 else None
    
    result = proxy_request(url, method=method, body=body)
    
    # Pretty print if it's a dict, otherwise just dump
    if isinstance(result, dict):
        print(json.dumps(result, indent=2))
    else:
        print(result)

if __name__ == "__main__":
    main()