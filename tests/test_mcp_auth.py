"""Tests for the origin-secret defense-in-depth middleware that protects the
hosted MCP server (App Runner) from being reached directly, bypassing API
Gateway's auth. This was previously only verified once, by hand, with curl,
against the real deployment during the build -- exactly the kind of thing
that should never rely on "I checked it once." Tests the actual middleware
logic locally via Starlette's TestClient, so it doesn't depend on the real
AWS deployment being up.
"""
import sys
from pathlib import Path

from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from external_service import mcp_server


def test_no_middleware_when_no_secret_configured(monkeypatch):
    """Local dev mode (no MCP_ORIGIN_SECRET set): requests aren't blocked."""
    monkeypatch.setattr(mcp_server, "ORIGIN_SECRET", None)
    # MCP's session manager needs the app's lifespan (startup/shutdown) to
    # actually run to initialize its task group -- TestClient only triggers
    # that as a context manager, not on plain instantiation.
    with TestClient(mcp_server.build_app()) as client:
        resp = client.post("/mcp", json={})
    assert resp.status_code != 403


def test_request_without_secret_header_rejected(monkeypatch):
    monkeypatch.setattr(mcp_server, "ORIGIN_SECRET", "test-secret")
    client = TestClient(mcp_server.build_app())
    resp = client.post("/mcp", json={})
    assert resp.status_code == 403
    assert "did not come through the gateway" in resp.text


def test_request_with_wrong_secret_rejected(monkeypatch):
    monkeypatch.setattr(mcp_server, "ORIGIN_SECRET", "test-secret")
    client = TestClient(mcp_server.build_app())
    resp = client.post("/mcp", json={}, headers={"x-origin-secret": "wrong-value"})
    assert resp.status_code == 403


def test_request_with_correct_secret_passes_middleware(monkeypatch):
    monkeypatch.setattr(mcp_server, "ORIGIN_SECRET", "test-secret")
    with TestClient(mcp_server.build_app()) as client:
        resp = client.post("/mcp", json={}, headers={"x-origin-secret": "test-secret"})
    # Past the middleware now -- reaches real MCP request validation instead
    # of the auth backstop, so it's a protocol error (400), never 403.
    assert resp.status_code != 403


def test_get_requests_also_enforced(monkeypatch):
    """The middleware wraps the whole app, not just POST -- confirm GET (used
    for SSE) is covered too."""
    monkeypatch.setattr(mcp_server, "ORIGIN_SECRET", "test-secret")
    client = TestClient(mcp_server.build_app())
    resp = client.get("/mcp")
    assert resp.status_code == 403
