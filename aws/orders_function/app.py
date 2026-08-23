"""Orders Lambda -- the same business logic as external_service/data_store.py,
ported to run against DynamoDB behind API Gateway instead of an in-memory
dict behind FastAPI. This is the real-AWS version of the same contract:
GET /orders/{id}, GET /orders/{id}/eligibility, POST /orders/{id}/returns.
"""
import json
import os
import random
from datetime import date, datetime, timezone
from decimal import Decimal

import boto3

TABLE_NAME = os.environ["ORDERS_TABLE"]
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def _to_jsonable(obj):
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(_to_jsonable(body)),
    }


def _get_order(order_id):
    resp = table.get_item(Key={"order_id": order_id.strip().upper()})
    return resp.get("Item")


def _eligibility(order, item_title=None):
    if order["status"] == "Cancelled":
        return {"eligible": False, "reason": "This order was already cancelled -- there's nothing to return."}
    if order["status"] != "Delivered" or not order.get("delivery_date"):
        return {
            "eligible": False,
            "reason": f"Order is currently '{order['status']}' and hasn't been delivered yet, so it isn't eligible for return (it can still be cancelled if not yet shipped -- escalate if needed).",
        }
    if not item_title and len(order["items"]) == 1:
        item_title = order["items"][0]["title"]
    if item_title:
        item = next((i for i in order["items"] if i["title"] == item_title), None)
        if not item:
            titles = [i["title"] for i in order["items"]]
            return {"eligible": False, "reason": f"'{item_title}' isn't in this order. Items on this order: {titles}."}
        if item.get("returned"):
            return {"eligible": False, "reason": f"'{item_title}' on this order has already been returned."}
        if item.get("format") == "ebook":
            return {"eligible": False, "reason": "E-books and other digital purchases are final sale and non-returnable."}
    delivered = date.fromisoformat(order["delivery_date"])
    days_since = (date.today() - delivered).days
    window = int(order["return_window_days"])
    if days_since > window:
        return {"eligible": False, "reason": f"Delivered {days_since} days ago, which is past the {window}-day return window."}
    return {
        "eligible": True,
        "reason": f"Delivered {days_since} days ago, within the {window}-day return window.",
        "days_remaining": window - days_since,
    }


def handler(event, context):
    method = event["requestContext"]["http"]["method"]
    order_id = (event.get("pathParameters") or {}).get("order_id", "").strip().upper()
    path = event["requestContext"]["http"]["path"]

    order = _get_order(order_id) if order_id else None

    if method == "GET" and path.endswith("/eligibility"):
        if not order:
            return _response(404, {"error": "not_found", "message": f"No order found with ID {order_id}."})
        item_title = (event.get("queryStringParameters") or {}).get("item_title")
        return _response(200, _eligibility(order, item_title))

    if method == "GET":
        if not order:
            return _response(404, {"error": "not_found", "message": f"No order found with ID {order_id}."})
        return _response(200, order)

    if method == "POST" and path.endswith("/returns"):
        if not order:
            return _response(422, {"error": "not_found", "message": f"No order found with ID {order_id}."})
        body = json.loads(event.get("body") or "{}")
        item_title, reason = body.get("item_title"), body.get("reason")
        elig = _eligibility(order, item_title)
        if not elig["eligible"]:
            return _response(422, {"error": "not_eligible", "message": elig["reason"]})

        items = order["items"]
        for i in items:
            if i["title"] == item_title:
                i["returned"] = True
        refund_amount = round(float(next(i["price"] for i in items if i["title"] == item_title)), 2)
        table.update_item(
            Key={"order_id": order_id},
            UpdateExpression="SET #items = :items",
            ExpressionAttributeNames={"#items": "items"},
            ExpressionAttributeValues={":items": items},
        )
        return_id = f"RT-{2000 + random.randint(1, 8999)}"
        return _response(
            200,
            {
                "return_id": return_id,
                "order_id": order_id,
                "item_title": item_title,
                "reason": reason,
                "refund_amount": refund_amount,
                "status": "label_sent",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    return _response(404, {"error": "not_found", "message": "No matching route."})
