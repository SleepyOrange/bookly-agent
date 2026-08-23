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


@pytest.fixture(autouse=True)
def clear_auth():
    """The module-level `client` persists cookies across requests (like a
    real browser) so login -> chat flows can be tested end to end -- which
    means a login cookie would otherwise leak from one test into the next
    sharing the same TestClient instance."""
    web.AUTH_SESSIONS.clear()
    client.cookies.clear()
    yield
    web.AUTH_SESSIONS.clear()
    client.cookies.clear()


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


def test_login_success_sets_cookie_and_returns_customer():
    resp = client.post("/api/login", json={"email": "alice@example.com", "password": "anything"})
    assert resp.status_code == 200
    assert resp.json() == {"email": "alice@example.com", "name": "Alice Nguyen"}
    assert web.AUTH_COOKIE in resp.cookies


def test_login_any_password_is_accepted():
    """Deliberate for this demo -- see the Login section comment in
    app/channels/web.py for why the password isn't actually checked."""
    resp = client.post("/api/login", json={"email": "bob@example.com", "password": "definitely-wrong"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "bob@example.com"


def test_login_unknown_email_rejected():
    resp = client.post("/api/login", json={"email": "nobody@example.com", "password": "x"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_credentials"


def test_login_is_case_insensitive_on_email():
    resp = client.post("/api/login", json={"email": "ALICE@EXAMPLE.COM", "password": "x"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"


def test_me_without_login_returns_401():
    resp = client.get("/api/me")
    assert resp.status_code == 401


def test_me_after_login_returns_customer():
    client.post("/api/login", json={"email": "alice@example.com", "password": "x"})
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Alice Nguyen"


def test_logout_clears_session_and_me_returns_401():
    client.post("/api/login", json={"email": "alice@example.com", "password": "x"})
    assert client.get("/api/me").status_code == 200

    resp = client.post("/api/logout")
    assert resp.status_code == 200
    assert client.get("/api/me").status_code == 401


def test_chat_picks_up_authenticated_email_from_cookie(monkeypatch):
    seen = []
    monkeypatch.setattr(web, "run_turn", lambda session, message: seen.append(session) or "ok")

    client.post("/api/login", json={"email": "alice@example.com", "password": "x"})
    client.post("/api/chat", json={"message": "hi"})

    assert seen[0].authenticated_email == "alice@example.com"


def test_chat_authenticated_email_is_none_when_not_logged_in(monkeypatch):
    seen = []
    monkeypatch.setattr(web, "run_turn", lambda session, message: seen.append(session) or "ok")

    client.post("/api/chat", json={"message": "hi"})

    assert seen[0].authenticated_email is None


def test_chat_reflects_logout_on_the_next_turn(monkeypatch):
    """authenticated_email is re-resolved every turn, not cached for the
    life of the chat session -- logging out mid-conversation should be
    reflected on the very next message, not require starting a new chat.
    Snapshots the value at call-time rather than the Session object itself,
    since the same object is reused across turns (see
    test_chat_reuses_existing_session_object) and would otherwise show the
    same (latest) state for both entries."""
    seen = []
    monkeypatch.setattr(web, "run_turn", lambda session, message: seen.append(session.authenticated_email) or "ok")

    client.post("/api/login", json={"email": "alice@example.com", "password": "x"})
    first = client.post("/api/chat", json={"message": "hi"}).json()
    client.post("/api/logout")
    client.post("/api/chat", json={"session_id": first["session_id"], "message": "still here?"})

    assert seen[0] == "alice@example.com"
    assert seen[1] is None
