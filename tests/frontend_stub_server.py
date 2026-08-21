"""Runs the real app.channels.web FastAPI app -- real routes, real static
files, real widget.js/index.html/contact.html -- with run_turn replaced by a
deterministic stub. This is what lets the Playwright frontend tests exercise
actual DOM/JS behavior (the thing no Python test can see) without needing a
live Anthropic API key or a real orchestrator round-trip: the frontend layer
doesn't care what produced the reply text, only that it got one.

Run standalone: python tests/frontend_stub_server.py [port]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

import app.channels.web as web


def stub_run_turn(session, message):
    """Canned replies keyed by substring, so deep-link/footer tests can
    assert on predictable text without a real model call."""
    lowered = message.lower()
    if "shipping" in lowered:
        return "Standard shipping is £4.99 (free over £35). Express is £12.99."
    if "return" in lowered and "policy" in lowered:
        return "You can return items within 30 days of delivery."
    if "order" in lowered:
        return "Could you share your order ID and the email on the order?"
    return f"Stub reply to: {message}"


web.run_turn = stub_run_turn

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8300
    uvicorn.run(web.app, host="127.0.0.1", port=port, log_level="warning")
