"""Channel layer: web chat. The same orchestrator/memory/actions stack would
back a voice or SMS channel too -- only this transport file would change.

Also owns the mock customer login (see the Login section below) -- this is
a channel/UI concern, not an orchestration one, so it stays entirely here
rather than leaking auth mechanics into app/orchestrator.py or app/actions.py.
The one place they meet is Session.authenticated_email (app/memory.py),
which is set here after reading the auth cookie and consumed by the
orchestrator to skip re-asking for the customer's email once logged in.
"""
import json
import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import store
from app.memory import Session
from app.orchestrator import run_turn

app = FastAPI(title="Bookly Concierge Agent")

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SESSIONS: dict[str, Session] = {}


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


# ---------- Login (mock: a real session mechanism, but password isn't
# actually checked -- see README's Login section for why that split is
# deliberate for this demo, and what a real deployment would add) ----------

AUTH_COOKIE = "bookly_auth"

with open(DATA_DIR / "customers.json") as f:
    CUSTOMERS = {c["email"].lower(): c for c in json.load(f)}

# token -> email. A real deployment would use a signed/expiring session
# (e.g. a JWT or a server-side store with TTLs) instead of a bare in-memory
# dict -- same "not production-hardened" caveat as SESSIONS above.
AUTH_SESSIONS: dict[str, str] = {}


class LoginRequest(BaseModel):
    email: str
    password: str


def _authenticated_email(request: Request) -> str | None:
    token = request.cookies.get(AUTH_COOKIE)
    return AUTH_SESSIONS.get(token) if token else None


@app.post("/api/login")
def login(body: LoginRequest, response: Response):
    email = body.email.strip().lower()
    customer = CUSTOMERS.get(email)
    if not customer:
        # Deliberately doesn't distinguish "no such account" from "wrong
        # password" in the message -- password isn't checked at all here,
        # but a real implementation would keep this generic for the same
        # reason: don't let a login form confirm which emails have accounts.
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_credentials", "message": "No account found for that email."},
        )
    token = secrets.token_urlsafe(32)
    AUTH_SESSIONS[token] = email
    response.set_cookie(AUTH_COOKIE, token, httponly=True, samesite="lax")
    return {"email": customer["email"], "name": customer["name"]}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(AUTH_COOKIE)
    if token:
        AUTH_SESSIONS.pop(token, None)
    response.delete_cookie(AUTH_COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    email = _authenticated_email(request)
    if not email:
        return JSONResponse(status_code=401, content={"error": "not_authenticated"})
    customer = CUSTOMERS[email]
    return {"email": customer["email"], "name": customer["name"]}


@app.get("/")
def storefront():
    """The Bookly storefront, with the support agent embedded as a floating
    widget (static/widget.js + widget.css) -- this is the actual "embed a
    chatbot on a real site" deliverable."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/chat")
def standalone_chat():
    """The agent as a full-page chat, no storefront around it -- useful for
    testing the agent in isolation."""
    return FileResponse(STATIC_DIR / "chat.html")


@app.get("/contact")
def contact():
    """A second page with the same embedded widget, to prove the widget is
    genuinely page-agnostic and not wired specifically to the storefront."""
    return FileResponse(STATIC_DIR / "contact.html")


@app.get("/api/catalog")
def catalog():
    return store.CATALOG


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    session_id = req.session_id or str(uuid.uuid4())
    session = SESSIONS.setdefault(session_id, Session())
    # Re-resolved every turn (cheap, idempotent) so logging in or out mid
    # conversation takes effect immediately, without needing a new chat session.
    session.authenticated_email = _authenticated_email(request)
    reply = run_turn(session, req.message)
    return ChatResponse(session_id=session_id, reply=reply)


@app.post("/api/reset")
def reset(session_id: str):
    SESSIONS.pop(session_id, None)
    return {"ok": True}
