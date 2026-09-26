import socket

import httpx
import pytest
from fastapi.testclient import TestClient

import app as app_module

TOKEN = {"X-Proxy-Token": "test-token"}


@pytest.fixture
def fake_dns(monkeypatch):
    records = {"example.com": ["93.184.216.34"], "rebind.test": ["10.0.0.5"],
               "mixed.test": ["93.184.216.34", "127.0.0.1"]}

    async def resolve(host):
        if host not in records:
            raise socket.gaierror("nope")
        return records[host]

    monkeypatch.setattr(app_module, "resolve_host", resolve)
    return records


@pytest.fixture
def client(fake_dns):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, text="ok")

    with TestClient(app_module.app) as c:
        app_module.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        c.seen = seen
        yield c


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://user@127.0.0.1:8000/",
    "http://[::1]:8000/",
    "http://[::ffff:127.0.0.1]/",
    "http://169.254.169.254/latest/meta-data/",
    "http://0.0.0.0/",
    "http://100.64.0.1/",          # CGNAT
    "http://metadata.google.internal/",
    "http://rebind.test/",
    "http://mixed.test/",           # any private record blocks
    "http://does-not-resolve.test/",
    "file:///etc/passwd",
    "http:///nohost",
])
def test_blocked_urls(client, url):
    r = client.post("/proxy", json={"url": url}, headers=TOKEN)
    assert r.status_code == 403, r.text
    assert client.seen == []


def test_bad_token(client):
    r = client.post("/proxy", json={"url": "http://example.com/"}, headers={"X-Proxy-Token": "nope"})
    assert r.status_code == 401


def test_request_is_pinned_to_validated_ip(client):
    r = client.post("/proxy", json={"url": "https://example.com:8443/path?q=1",
                                    "headers": {"Host": "evil.internal"}}, headers=TOKEN)
    assert r.status_code == 200, r.text
    (req,) = client.seen
    assert req.url.host == "93.184.216.34"
    assert req.url.port == 8443
    assert req.url.raw_path == b"/path?q=1"
    assert req.headers["host"] == "example.com:8443"
    assert req.extensions["sni_hostname"] == "example.com"


def test_allowlist_uses_hostname(client, monkeypatch):
    monkeypatch.setattr(app_module, "ALLOWED_DOMAINS", ["example.com"])
    ok = client.post("/proxy", json={"url": "http://user@example.com:80/"}, headers=TOKEN)
    assert ok.status_code == 200, ok.text
    for url in ["http://example.com@evil.test/", "http://notexample.com/"]:
        r = client.post("/proxy", json={"url": url}, headers=TOKEN)
        assert r.status_code == 403, url
