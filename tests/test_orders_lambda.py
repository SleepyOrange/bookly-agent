"""Tests for the AWS orders Lambda (aws/orders_function/app.py) -- the code
actually running in production, previously verified only by hand against
the real deployment. No AWS credentials or network needed: table.get_item /
table.update_item are the only two DynamoDB calls this handler makes, so a
small in-memory fake table is enough to exercise the real handler logic
(event parsing, eligibility rules, Decimal->JSON conversion) without pulling
in a mocking framework like moto for two methods.
"""
import copy
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

os.environ.setdefault("ORDERS_TABLE", "test-bookly-orders")
from aws.orders_function import app as lambda_app  # noqa: E402


class FakeTable:
    def __init__(self, items):
        self._items = {k: copy.deepcopy(v) for k, v in items.items()}

    def get_item(self, Key):
        item = self._items.get(Key["order_id"])
        return {"Item": copy.deepcopy(item)} if item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        assert UpdateExpression == "SET #items = :items"
        self._items[Key["order_id"]]["items"] = ExpressionAttributeValues[":items"]


SAMPLE_ORDERS = {
    "BK-10234": {
        "order_id": "BK-10234",
        "customer_email": "alice@example.com",
        "customer_name": "Alice Nguyen",
        "items": [{"title": "Project Hail Mary", "author": "Andy Weir", "qty": 1, "price": Decimal("14.99"), "format": "print", "returned": False}],
        "order_date": "2026-08-05",
        "status": "Delivered",
        "delivery_date": "2026-08-09",
        "tracking_number": "1Z999AA10123456784",
        "carrier": "UPS",
        "return_window_days": Decimal("30"),
    },
    "BK-12010": {
        "order_id": "BK-12010",
        "customer_email": "alice@example.com",
        "customer_name": "Alice Nguyen",
        "items": [{"title": "Digital Fortress", "author": "Dan Brown", "qty": 1, "price": Decimal("7.99"), "format": "ebook", "returned": False}],
        "order_date": "2026-08-10",
        "status": "Delivered",
        "delivery_date": "2026-08-10",
        "tracking_number": None,
        "carrier": None,
        "return_window_days": Decimal("30"),
    },
}


@pytest.fixture(autouse=True)
def fake_table(monkeypatch):
    monkeypatch.setattr(lambda_app, "table", FakeTable(SAMPLE_ORDERS))


def _event(method, path, order_id=None, query=None, body=None):
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "pathParameters": {"order_id": order_id} if order_id else {},
        "queryStringParameters": query,
        "body": json.dumps(body) if body is not None else None,
    }


def test_get_order_found():
    resp = lambda_app.handler(_event("GET", "/orders/BK-10234", order_id="BK-10234"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["customer_email"] == "alice@example.com"
    assert body["items"][0]["price"] == 14.99  # Decimal -> float conversion


def test_get_order_not_found():
    resp = lambda_app.handler(_event("GET", "/orders/BK-99999", order_id="BK-99999"), None)
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_eligibility_within_window():
    resp = lambda_app.handler(_event("GET", "/orders/BK-10234/eligibility", order_id="BK-10234"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["eligible"] is True


def test_eligibility_ebook_rejected():
    event = _event("GET", "/orders/BK-12010/eligibility", order_id="BK-12010", query={"item_title": "Digital Fortress"})
    resp = lambda_app.handler(event, None)
    body = json.loads(resp["body"])
    assert body["eligible"] is False
    assert "final sale" in body["reason"]


def test_create_return_success_and_persists_via_update_item():
    event = _event("POST", "/orders/BK-10234/returns", order_id="BK-10234", body={"item_title": "Project Hail Mary", "reason": "N/A"})
    resp = lambda_app.handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["refund_amount"] == 14.99
    assert body["return_id"].startswith("RT-")

    # returned flag should now be persisted in the (fake) table
    resp2 = lambda_app.handler(_event("GET", "/orders/BK-10234", order_id="BK-10234"), None)
    assert json.loads(resp2["body"])["items"][0]["returned"] is True


def test_create_return_unknown_order_returns_422():
    event = _event("POST", "/orders/BK-99999/returns", order_id="BK-99999", body={"item_title": "X", "reason": "N/A"})
    resp = lambda_app.handler(event, None)
    assert resp["statusCode"] == 422
    assert json.loads(resp["body"])["error"] == "not_found"


def test_unmatched_route_returns_404():
    resp = lambda_app.handler(_event("DELETE", "/orders/BK-10234", order_id="BK-10234"), None)
    assert resp["statusCode"] == 404
