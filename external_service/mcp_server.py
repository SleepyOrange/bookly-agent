"""Bookly External API, wrapped as an MCP server -- Decagon's tier-3
integration pattern ("an open standard allowing connection to any data
system... for real-time data and actions"), sitting alongside the tier-2
REST API (main.py) rather than replacing it. Same business logic
(external_service/data_store.py), same four operations, different wire
protocol: JSON-RPC over streamable HTTP instead of plain REST.

Run standalone: python -m external_service.mcp_server (defaults to
127.0.0.1:8200, MCP endpoint at /mcp).
"""
from mcp.server.mcpserver import MCPServer

from external_service import data_store

mcp = MCPServer(name="bookly-external", version="1.0.0")


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
def search_policy(query: str) -> dict:
    """Search Bookly's FAQ/policy content with a free-text question. Returns
    ranked matches, or error='no_match' if nothing relevant was found."""
    matches = data_store.search_policy(query)
    if not matches:
        return {"error": "no_match", "message": "No relevant policy content found."}
    return {"query": query, "matches": matches}


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8200)
