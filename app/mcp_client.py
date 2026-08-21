"""Sync bridge to an MCP server (external_service/mcp_server.py, or any real
MCP-hosted endpoint later). app/store.py, actions.py, knowledge.py, and
guardrails.py are all synchronous by design, matching the orchestrator's
synchronous tool-use loop -- but the MCP SDK's client is async-only.

Rather than making the whole call chain async just for this one transport
option, this runs a single persistent event loop on a background thread and
bridges sync calls into it: the same shape FastAPI's TestClient uses to let
sync test code call an async ASGI app. The MCP session connects once, lazily,
on first use, and stays open for the process lifetime.
"""
import asyncio
import json
import os
import threading

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_URL = os.environ.get("BOOKLY_MCP_SERVER_URL", "http://127.0.0.1:8200/mcp")

_loop: asyncio.AbstractEventLoop | None = None
_session: ClientSession | None = None
_init_lock = threading.Lock()
_init_error: Exception | None = None

# Kept alive deliberately: these are async context managers entered by hand
# (not via `async with`) so the connection can outlive the coroutine that
# opened it. Without a strong reference here, the streamable_http_client
# generator gets garbage-collected shortly after _connect() returns, which
# silently tears the session down (it did, the first time -- a DELETE
# /mcp shows up in the server log a moment after the first successful call).
_streams_cm = None
_session_cm = None


def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def _connect():
    global _session, _streams_cm, _session_cm
    _streams_cm = streamable_http_client(MCP_SERVER_URL)
    read, write, *_ = await _streams_cm.__aenter__()
    _session_cm = ClientSession(read, write)
    session = await _session_cm.__aenter__()
    await session.initialize()
    _session = session


def _ensure_started():
    global _loop, _init_error
    with _init_lock:
        if _loop is not None or _init_error is not None:
            return
        loop = asyncio.new_event_loop()
        threading.Thread(target=_run_loop, args=(loop,), daemon=True).start()
        try:
            asyncio.run_coroutine_threadsafe(_connect(), loop).result(timeout=10)
            _loop = loop
        except Exception as exc:  # server not running, wrong URL, etc.
            _init_error = exc


def call_tool(name: str, arguments: dict) -> dict:
    _ensure_started()
    if _init_error is not None:
        return {
            "error": "external_service_unavailable",
            "message": f"Couldn't reach the MCP server at {MCP_SERVER_URL} ({_init_error.__class__.__name__}).",
        }
    try:
        result = asyncio.run_coroutine_threadsafe(
            _session.call_tool(name, arguments), _loop
        ).result(timeout=10)
    except Exception as exc:
        return {"error": "external_service_unavailable", "message": f"MCP call failed ({exc.__class__.__name__})."}
    if not result.content:
        return {}
    return json.loads(result.content[0].text)
