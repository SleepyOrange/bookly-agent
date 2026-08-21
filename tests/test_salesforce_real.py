"""Tests for the real Salesforce integration path (OAuth Client Credentials
Flow + Case creation) in app/salesforce.py. httpx.post/get are monkeypatched
module-wide for the duration of each test -- reverted automatically after --
so these need no real Salesforce org or network access, same principle as
the AWS Lambda handler tests.
"""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import salesforce


def _resp(status, json_body, method="POST", url="https://example.my.salesforce.com/x"):
    return httpx.Response(status, json=json_body, request=httpx.Request(method, url))


@pytest.fixture(autouse=True)
def real_mode(monkeypatch):
    monkeypatch.setattr(salesforce, "MODE", "real")
    monkeypatch.setattr(salesforce, "INSTANCE_URL", "https://example.my.salesforce.com")
    monkeypatch.setattr(salesforce, "CLIENT_ID", "test-client-id")
    monkeypatch.setattr(salesforce, "CLIENT_SECRET", "test-client-secret")
    salesforce.reset()
    yield
    salesforce.reset()


def test_real_case_creation_full_flow(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(("POST", url, kwargs))
        if url.endswith("/services/oauth2/token"):
            return _resp(200, {"access_token": "tok-123", "instance_url": "https://example.my.salesforce.com"})
        if url.endswith("/sobjects/Case"):
            return _resp(201, {"id": "500XX000001abcAAA", "success": True, "errors": []})
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        return _resp(
            200,
            {
                "CaseNumber": "00001234",
                "Subject": "Bookly escalation: test",
                "Description": "test",
                "Status": "New",
                "Origin": "Chat",
                "Priority": "Medium",
                "CreatedDate": "2026-08-21T12:00:00.000+0000",
            },
            method="GET",
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    result = salesforce.create_case("Bookly escalation: test", "test", origin="Chat", priority="Medium")

    assert result["Id"] == "500XX000001abcAAA"
    assert result["CaseNumber"] == "00001234"
    assert any(m == "POST" and u.endswith("/services/oauth2/token") for m, u, _ in calls)
    assert any(m == "POST" and u.endswith("/sobjects/Case") for m, u, _ in calls)
    # the Case POST must carry the token as a Bearer header
    case_call = next(kwargs for m, u, kwargs in calls if u.endswith("/sobjects/Case"))
    assert case_call["headers"]["Authorization"] == "Bearer tok-123"


def test_token_is_cached_across_calls(monkeypatch):
    token_calls = {"count": 0}

    def fake_post(url, **kwargs):
        if url.endswith("/services/oauth2/token"):
            token_calls["count"] += 1
            return _resp(200, {"access_token": "tok-123", "instance_url": "https://example.my.salesforce.com"})
        return _resp(201, {"id": "500XX000001abcAAA", "success": True, "errors": []})

    def fake_get(url, **kwargs):
        return _resp(200, {"CaseNumber": "00001234", "Status": "New", "Origin": "Chat", "Priority": "Medium", "CreatedDate": "x"})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    salesforce.create_case("A", "a")
    salesforce.create_case("B", "b")

    assert token_calls["count"] == 1, "second call should reuse the cached token, not refetch"


def test_401_triggers_token_refresh_and_retry(monkeypatch):
    state = {"token_fetches": 0, "case_posts": 0}

    def fake_post(url, **kwargs):
        if url.endswith("/services/oauth2/token"):
            state["token_fetches"] += 1
            return _resp(200, {"access_token": f"tok-{state['token_fetches']}", "instance_url": "https://example.my.salesforce.com"})
        state["case_posts"] += 1
        if state["case_posts"] == 1:
            return _resp(401, {"message": "Session expired"})
        return _resp(201, {"id": "500XX000001abcAAA", "success": True, "errors": []})

    def fake_get(url, **kwargs):
        return _resp(200, {"CaseNumber": "00001234", "Status": "New", "Origin": "Chat", "Priority": "Medium", "CreatedDate": "x"})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    result = salesforce.create_case("A", "a")

    assert state["token_fetches"] == 2  # initial + refresh after 401
    assert state["case_posts"] == 2  # failed attempt + successful retry
    assert result["Id"] == "500XX000001abcAAA"


def test_falls_back_to_mock_when_salesforce_unreachable(monkeypatch):
    def fake_post(url, **kwargs):
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)

    result = salesforce.create_case("A", "a")
    assert result["Id"].startswith("500")  # got a case back anyway, from the mock
    assert result["CaseNumber"] == "00000001"


def test_fallback_can_be_disabled(monkeypatch):
    monkeypatch.setattr(salesforce, "ENABLE_FALLBACK", False)

    def fake_post(url, **kwargs):
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(httpx.ConnectError):
        salesforce.create_case("A", "a")


def test_real_mode_without_credentials_raises_and_falls_back(monkeypatch):
    monkeypatch.setattr(salesforce, "CLIENT_ID", None)
    result = salesforce.create_case("A", "a")
    assert result["Id"].startswith("500")  # fell back to mock rather than crashing the escalation
