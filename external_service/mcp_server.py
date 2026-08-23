"""Bookly External API, wrapped as an MCP server -- Decagon's tier-3
integration pattern ("an open standard allowing connection to any data
system... for real-time data and actions"), sitting alongside the tier-2
REST API (main.py) rather than replacing it. Same business logic
(external_service/data_store.py), same four operations, different wire
protocol: JSON-RPC over streamable HTTP instead of plain REST.

Run standalone: python -m external_service.mcp_server (defaults to
127.0.0.1:8200, MCP endpoint at /mcp).

When hosted publicly (aws/mcp_apprunner/), API Gateway sits in front with an
API key and injects a shared secret header on every request it proxies
through. MCP_ORIGIN_SECRET here checks for that header, so a request that
reaches this service *without* going through API Gateway -- someone who
found the App Runner URL directly -- gets rejected. Auth (the API key)
happens at the gateway; this is the defense-in-depth backstop against
bypassing it, not the auth mechanism itself.
"""
import os

from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from external_service import data_store

mcp = MCPServer(name="bookly-external", version="1.0.0")

ORIGIN_SECRET = os.environ.get("MCP_ORIGIN_SECRET")


class OriginSecretMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("x-origin-secret") != ORIGIN_SECRET:
            return PlainTextResponse("Forbidden -- request did not come through the gateway", status_code=403)
        return await call_next(request)


@mcp.tool()
def get_order(order_id: str) -> dict:
    """Look up a Bookly order by ID. Returns the full order record, or an
    error dict with error='not_found' if no such order exists."""
    order = data_store.find_order(order_id)
    if not order:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}
    return order


@mcp.tool()
def check_eligibility(order_id: str, item_title: str | None = None) -> dict:
    """Check return eligibility for an order, or a specific item on it."""
    order = data_store.find_order(order_id)
    if not order:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}
    return data_store.eligibility(order_id, item_title)


@mcp.tool()
def create_return(order_id: str, item_title: str, reason: str) -> dict:
    """Create a return for a specific item on an order. Fails with
    error='not_eligible' if the item isn't returnable right now."""
    return data_store.create_return(order_id, item_title, reason)


@mcp.tool()
def cancel_return(order_id: str, return_id: str) -> dict:
    """Cancel a previously-initiated return (voids the label, no refund
    issued), as long as it hasn't already been cancelled or processed.
    Fails with error='not_found' or error='not_cancellable' as appropriate."""
    return data_store.cancel_return(order_id, return_id)


@mcp.tool()
def search_policy(query: str) -> dict:
    """Search Bookly's FAQ/policy content with a free-text question. Returns
    ranked matches, or error='no_match' if nothing relevant was found."""
    matches = data_store.search_policy(query)
    if not matches:
        return {"error": "no_match", "message": "No relevant policy content found."}
    return {"query": query, "matches": matches}


def build_app():
    """The Starlette ASGI app, wrapped with the origin-secret check when one
    is configured. Used by the container entrypoint (below) and importable
    directly for e.g. `uvicorn external_service.mcp_server:build_app --factory`."""
    app = mcp.streamable_http_app(host="0.0.0.0")
    if ORIGIN_SECRET:
        app.add_middleware(OriginSecretMiddleware)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8200"))
    if ORIGIN_SECRET:
        # Container/AWS mode: bind all interfaces, enforce the origin secret.
        import uvicorn

        uvicorn.run(build_app(), host="0.0.0.0", port=port)
    else:
        # Local dev: unchanged from before.
        mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
