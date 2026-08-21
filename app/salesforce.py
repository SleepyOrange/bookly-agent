"""Salesforce Case integration -- the escalation/handoff boundary.

This follows Decagon's own documented Salesforce pattern: connect via OAuth,
sync knowledge base + historical tickets, and escalate by creating a
Salesforce Case so a human agent picks it up in the tool they already work
in, not a separate queue. (See the take-home notes on
docs.decagon.ai/connecting-decagon-to-salesforce and
decagon.ai/product/integrations.)

Two modes, picked via BOOKLY_SALESFORCE_MODE (default "mock"):
- "mock": in-memory record shaped like a real Salesforce Case object.
- "real": OAuth 2.0 Client Credentials Flow against a Connected App, then a
  real POST to /services/data/vXX.X/sobjects/Case/.
app/handoff.py only ever sees "create a case, get back an id/number" --
identical either way, so nothing above this module changed for the swap.

Real mode defaults to production being something you opt into deliberately:
mock stays the default even if credentials are present, unless
BOOKLY_SALESFORCE_MODE=real is set explicitly. If the real API is
unreachable (network, auth failure, permission error), this falls back to
the same in-memory mock rather than losing the escalation entirely -- the
same resilience pattern app/store.py uses for orders/FAQ. Disable with
BOOKLY_ENABLE_FALLBACK=false (shared with app/store.py's flag).
"""
import logging
import os
import secrets
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("bookly.salesforce")

MODE = os.environ.get("BOOKLY_SALESFORCE_MODE", "mock")
ENABLE_FALLBACK = os.environ.get("BOOKLY_ENABLE_FALLBACK", "true").lower() != "false"

INSTANCE_URL = os.environ.get("SALESFORCE_INSTANCE_URL", "").rstrip("/")
CLIENT_ID = os.environ.get("SALESFORCE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SALESFORCE_CLIENT_SECRET")
API_VERSION = os.environ.get("SALESFORCE_API_VERSION", "v61.0")

_CASES = {}
_next_case_number = 1

_token_cache = {"access_token": None, "instance_url": None, "fetched_at": 0}
_TOKEN_MAX_AGE_SECONDS = 25 * 60  # refetch well before Salesforce would ever expire it


def _create_case_mock(subject: str, description: str, origin: str, priority: str) -> dict:
    global _next_case_number
    case_id = "500" + secrets.token_hex(8).upper()[:15]  # Case object prefix + mock 18-char id
    case_number = f"{_next_case_number:08d}"  # matches Salesforce's zero-padded CaseNumber format
    _next_case_number += 1
    record = {
        "Id": case_id,
        "CaseNumber": case_number,
        "Subject": subject,
        "Description": description,
        "Status": "New",
        "Origin": origin,
        "Priority": priority,
        "CreatedDate": datetime.now(timezone.utc).isoformat(),
    }
    _CASES[case_id] = record
    return record


def _get_access_token(force_refresh: bool = False) -> tuple[str, str]:
    """Returns (access_token, instance_url), fetching/caching via the OAuth
    2.0 Client Credentials Flow. Uses the instance_url Salesforce returns in
    the token response, not SALESFORCE_INSTANCE_URL, since Salesforce
    sometimes routes it to a different (equivalent) pod URL."""
    age = time.time() - _token_cache["fetched_at"]
    if not force_refresh and _token_cache["access_token"] and age < _TOKEN_MAX_AGE_SECONDS:
        return _token_cache["access_token"], _token_cache["instance_url"]

    resp = httpx.post(
        f"{INSTANCE_URL}/services/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    body = resp.json()
    _token_cache.update(
        access_token=body["access_token"],
        instance_url=body["instance_url"],
        fetched_at=time.time(),
    )
    return _token_cache["access_token"], _token_cache["instance_url"]


def _create_case_real(subject: str, description: str, origin: str, priority: str) -> dict:
    if not (INSTANCE_URL and CLIENT_ID and CLIENT_SECRET):
        raise RuntimeError(
            "BOOKLY_SALESFORCE_MODE=real requires SALESFORCE_INSTANCE_URL, "
            "SALESFORCE_CLIENT_ID, and SALESFORCE_CLIENT_SECRET to be set."
        )

    access_token, instance_url = _get_access_token()
    sobjects_url = f"{instance_url}/services/data/{API_VERSION}/sobjects/Case"

    def _post():
        return httpx.post(
            sobjects_url,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"Subject": subject, "Description": description, "Origin": origin, "Priority": priority},
            timeout=10.0,
        )

    resp = _post()
    if resp.status_code == 401:
        # token expired/revoked server-side before our cache thought it would -- refresh once and retry
        access_token, instance_url = _get_access_token(force_refresh=True)
        sobjects_url = f"{instance_url}/services/data/{API_VERSION}/sobjects/Case"
        resp = _post()
    resp.raise_for_status()
    case_id = resp.json()["id"]

    # The create response only returns {id, success, errors} -- Salesforce
    # assigns CaseNumber server-side, so fetch the record back to get the
    # shape app/handoff.py expects (matches the mock's contract exactly).
    get_resp = httpx.get(
        f"{instance_url}/services/data/{API_VERSION}/sobjects/Case/{case_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"fields": "CaseNumber,Subject,Description,Status,Origin,Priority,CreatedDate"},
        timeout=10.0,
    )
    get_resp.raise_for_status()
    record = get_resp.json()
    record["Id"] = case_id
    return record


def create_case(subject: str, description: str, origin: str = "Chat", priority: str = "Medium") -> dict:
    """Returns a dict shaped like Salesforce's Case object (Id, CaseNumber,
    Subject, Description, Status, Origin, Priority, CreatedDate)."""
    if MODE != "real":
        return _create_case_mock(subject, description, origin, priority)
    try:
        return _create_case_real(subject, description, origin, priority)
    except Exception as exc:
        if not ENABLE_FALLBACK:
            raise
        logger.warning(
            "Real Salesforce Case creation failed (%s: %s); falling back to local mock.",
            exc.__class__.__name__,
            exc,
        )
        return _create_case_mock(subject, description, origin, priority)


def reset():
    """Test hook: clears all mock cases and the cached OAuth token."""
    global _CASES, _next_case_number
    _CASES = {}
    _next_case_number = 1
    _token_cache.update(access_token=None, instance_url=None, fetched_at=0)
