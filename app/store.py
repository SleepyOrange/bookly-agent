"""Client for the Bookly External API (external_service/) -- the "external
system" that owns order and FAQ data. This is the ONLY module in the agent
that knows the external system exists; actions.py, knowledge.py, and
guardrails.py only call functions here and don't know or care whether the
data came from a network call, an MCP tool call, or a local dict.

Two transports, same contract, picked via BOOKLY_TRANSPORT:
- "rest" (default): plain HTTP against external_service/main.py or aws/.
- "mcp": JSON-RPC against external_service/mcp_server.py via app/mcp_client.py.
Both return identical response shapes -- that's what makes this a config
change, not a rewrite, when swapping between them.

Deliberately NOT delegated to the external service, on either transport:
identity/access control. guardrails.verify_identity() still runs entirely
in our process against whatever find_order() returns -- we never trust an
upstream system to enforce our own security model.

Resilience: if the configured primary (REST or MCP, local or AWS) is
unreachable, every function here falls back to external_service/data_store.py
called directly in-process -- a real, always-available mock, not just a
graceful error. This is a genuine trade-off, not a free lunch: the fallback's
data is whatever's in the local JSON fixture, which can drift from a real
AWS backend's live state (e.g. a return recorded during a fallback window
won't exist in DynamoDB once the primary comes back). Good enough to keep
answering customers through a real outage; not a substitute for the primary
coming back and reconciling. Set BOOKLY_ENABLE_FALLBACK=false to disable and
get the old fail-loud behavior instead (see app/prompts.py's handling of
external_service_unavailable).

The product catalog (data/catalog.json) is unrelated storefront content, not
part of this integration, so it stays a local fixture loaded directly.
"""
import json
import logging
import os
from pathlib import Path

import httpx

from app import mcp_client
from external_service import data_store as fallback_store

logger = logging.getLogger("bookly.store")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

with open(DATA_DIR / "catalog.json") as f:
    CATALOG = json.load(f)

TRANSPORT = os.environ.get("BOOKLY_TRANSPORT", "rest")
EXTERNAL_API_URL = os.environ.get("BOOKLY_EXTERNAL_API_URL", "http://127.0.0.1:8100")
ENABLE_FALLBACK = os.environ.get("BOOKLY_ENABLE_FALLBACK", "true").lower() != "false"

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=EXTERNAL_API_URL, timeout=5.0)
    return _client


def set_client(client: httpx.Client):
    """Test hook: inject a client wired to an in-process ASGI transport
    instead of a real network connection (see tests/conftest.py). REST
    transport only -- MCP tests spin up a real (local) server instead."""
    global _client
    _client = client


def _unavailable(exc: Exception):
    return {
        "error": "external_service_unavailable",
        "message": f"Couldn't reach the order system right now ({exc.__class__.__name__}).",
    }


def _is_unavailable(result) -> bool:
    return isinstance(result, dict) and result.get("error") == "external_service_unavailable"


def find_order(order_id: str):
    order_id = order_id.strip().upper()
    result = _find_order_primary(order_id)
    if ENABLE_FALLBACK and _is_unavailable(result):
        logger.warning("Primary order service unavailable; falling back to local mock for %s", order_id)
        order = fallback_store.find_order(order_id)
        return order if order else {"error": "not_found", "message": f"No order found with ID {order_id}."}
    return result


def _find_order_primary(order_id: str):
    if TRANSPORT == "mcp":
        return mcp_client.call_tool("get_order", {"order_id": order_id})
    try:
        resp = _get_client().get(f"/orders/{order_id}")
    except httpx.RequestError as exc:
        return _unavailable(exc)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def check_eligibility(order_id: str, item_title: str | None = None):
    order_id = order_id.strip().upper()
    result = _check_eligibility_primary(order_id, item_title)
    if ENABLE_FALLBACK and _is_unavailable(result):
        logger.warning("Primary order service unavailable; falling back to local mock for %s", order_id)
        order = fallback_store.find_order(order_id)
        if not order:
            return {"error": "not_found", "message": f"No order found with ID {order_id}."}
        return fallback_store.eligibility(order_id, item_title)
    return result


def _check_eligibility_primary(order_id: str, item_title: str | None):
    if TRANSPORT == "mcp":
        args = {"order_id": order_id}
        if item_title:
            args["item_title"] = item_title
        return mcp_client.call_tool("check_eligibility", args)
    try:
        params = {"item_title": item_title} if item_title else {}
        resp = _get_client().get(f"/orders/{order_id}/eligibility", params=params)
    except httpx.RequestError as exc:
        return _unavailable(exc)
    if resp.status_code == 404:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}
    resp.raise_for_status()
    return resp.json()


def create_return(order_id: str, item_title: str, reason: str):
    order_id = order_id.strip().upper()
    result = _create_return_primary(order_id, item_title, reason)
    if ENABLE_FALLBACK and _is_unavailable(result):
        logger.warning("Primary order service unavailable; falling back to local mock for %s", order_id)
        return fallback_store.create_return(order_id, item_title, reason)
    return result


def _create_return_primary(order_id: str, item_title: str, reason: str):
    if TRANSPORT == "mcp":
        return mcp_client.call_tool("create_return", {"order_id": order_id, "item_title": item_title, "reason": reason})
    try:
        resp = _get_client().post(
            f"/orders/{order_id}/returns",
            json={"item_title": item_title, "reason": reason},
        )
    except httpx.RequestError as exc:
        return _unavailable(exc)
    if resp.status_code == 422:
        return resp.json()["detail"]
    if resp.status_code == 404:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}
    resp.raise_for_status()
    return resp.json()


def search_policy(query: str):
    """Returns (matches, err). matches is a list of {"text", "score"} dicts,
    most relevant first -- real semantic retrieval against a Bedrock
    Knowledge Base in AWS, or a lexical stand-in for local dev (see
    external_service/data_store.py). Either way, callers never see the
    difference."""
    matches, err = _search_policy_primary(query)
    if ENABLE_FALLBACK and err is not None and err.get("error") == "external_service_unavailable":
        logger.warning("Primary FAQ service unavailable; falling back to local lexical search for %r", query)
        return fallback_store.search_policy(query), None
    return matches, err


def _search_policy_primary(query: str):
    if TRANSPORT == "mcp":
        result = mcp_client.call_tool("search_policy", {"query": query})
        if result.get("error") == "no_match":
            return [], None
        if "error" in result:
            return None, result
        return result["matches"], None
    try:
        resp = _get_client().get("/faq", params={"q": query})
    except httpx.RequestError as exc:
        return None, _unavailable(exc)
    if resp.status_code == 404:
        return [], None
    resp.raise_for_status()
    return resp.json()["matches"], None
