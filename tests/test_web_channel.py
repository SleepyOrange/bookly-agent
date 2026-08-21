"""Tests for the web channel (app/channels/web.py) -- the actual HTTP
surface every real request goes through, and previously the least-tested
part of the whole system despite being the most-used. run_turn is
monkeypatched so these stay fast and offline; the orchestrator itself is
already covered by tests/test_conversations.py (live) and the
layer-specific unit tests.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.channels.web as web

client = TestClient(web.app)


@pytest.fixture(autouse=True)
def clear_sessions():
    web.SESSIONS.clear()
    yield
    web.SESSIONS.clear()


def test_storefront_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_standalone_chat_served():
    resp = client.get("/chat")
    assert resp.status_code == 200


def test_contact_page_served():
    resp = client.get("/contact")
    assert resp.status_code == 200


def test_static_assets_served():
    resp = client.get("/static/widget.js")
    assert resp.status_code == 200


def test_catalog_returns_books():
    resp = client.get("/api/catalog")
    assert resp.status_code == 200
    books = resp.json()
    assert len(books) > 0
    assert "title" in books[0] and "price" in books[0]


def test_chat_creates_new_session_when_none_given(monkeypatch):
    monkeypatch.setattr(web, "run_turn", lambda session, message: f"echo: {message}")
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "echo: hello"
    assert body["session_id"]
    assert body["session_id"] in web.SESSIONS


def test_chat_reuses_existing_session_object(monkeypatch):
    seen = []
    monkeypatch.setattr(web, "run_turn", lambda session, message: seen.append(session) or "ok")

    first = client.post("/api/chat", json={"message": "hi"}).json()
    session_id = first["session_id"]
    client.post("/api/chat", json={"session_id": session_id, "message": "again"})

    assert len(seen) == 2
    assert seen[0] is seen[1]  # same Session object reused across turns, not recreated


def test_reset_removes_session(monkeypatch):
    monkeypatch.setattr(web, "run_turn", lambda session, message: "ok")
    session_id = client.post("/api/chat", json={"message": "hi"}).json()["session_id"]
    assert session_id in web.SESSIONS

    resp = client.post("/api/reset", params={"session_id": session_id})
    assert resp.status_code == 200
    assert session_id not in web.SESSIONS
