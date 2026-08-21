"""Tests for the external service (external_service/) on its own terms --
independent of the Bookly agent, the same way you'd test any real upstream
system's API before trusting an integration against it.
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from external_service.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_get_order_found():
    resp = client.get("/orders/BK-10234")
    assert resp.status_code == 200
    assert resp.json()["customer_email"] == "alice@example.com"


def test_get_order_not_found():
    resp = client.get("/orders/BK-99999")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "not_found"


def test_eligibility_within_window():
    resp = client.get("/orders/BK-10234/eligibility")
    assert resp.status_code == 200
    assert resp.json()["eligible"] is True


def test_eligibility_ebook_rejected():
    resp = client.get("/orders/BK-12010/eligibility", params={"item_title": "Digital Fortress"})
    assert resp.json()["eligible"] is False
    assert "final sale" in resp.json()["reason"]


def test_create_return_success_and_marks_item_returned():
    resp = client.post("/orders/BK-10234/returns", json={"item_title": "Project Hail Mary", "reason": "N/A"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["refund_amount"] == 14.99
    assert body["return_id"].startswith("RT-")

    # a second attempt on the same item should now be rejected
    resp2 = client.post("/orders/BK-10234/returns", json={"item_title": "Project Hail Mary", "reason": "N/A"})
    assert resp2.status_code == 422
    assert "already been returned" in resp2.json()["detail"]["message"]


def test_create_return_unknown_order():
    resp = client.post("/orders/BK-99999/returns", json={"item_title": "X", "reason": "N/A"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "not_found"


def test_faq_search_relevant_query():
    resp = client.get("/faq", params={"q": "how long do I have to return an item"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"]
    assert any("30 days" in m["text"] for m in body["matches"])
    # ranked, most relevant first
    assert body["matches"] == sorted(body["matches"], key=lambda m: -m["score"])


def test_faq_search_no_match():
    resp = client.get("/faq", params={"q": "xyzzy quux plugh nonsense query"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "no_match"


def test_faq_search_requires_query():
    resp = client.get("/faq")
    assert resp.status_code == 422  # FastAPI validation: q is required
