"""MCP server exposing ICA Handla as tools for LLM clients (Claude, etc.).

This is a thin wrapper over the existing ``IcaApi`` / ``HandlaClient`` layer.
The MCP SDK (``mcp``) is an **optional** dependency (``pip install '.[mcp]'``):
the tool functions below are plain and import-safe, and only ``build_server()``
touches ``mcp``, so the rest of the package works without it.

Authentication is handled out-of-band: run ``ica login`` (and, for cart tools,
``ica handla login``) in a terminal once. The server reads the saved session
from ``state.json`` — it never asks the model for your password.

Run it:  ``ica-handla-mcp``  or  ``python -m ica_handla.mcp_server`` (stdio).
"""
from __future__ import annotations

import functools
from typing import Any, Callable, Optional

from . import handla as handla_mod
from .api import IcaApi
from .auth import Authenticator
from .config import State
from .errors import IcaError


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _api() -> IcaApi:
    return IcaApi(Authenticator(State.load()))


def _handla(store_id: Optional[str], *, need_cookie: bool) -> handla_mod.HandlaClient:
    st = State.load()
    sid = handla_mod.resolve_store_id(st, store_id)
    cookie = handla_mod.resolve_cookie(st) if need_cookie else None
    return handla_mod.HandlaClient(sid, cookie_header=cookie, state=st)


def _safe(fn: Callable) -> Callable:
    """Turn IcaError into a structured result instead of a raw exception."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return {"ok": True, "data": fn(*a, **k)}
        except IcaError as e:
            return {"ok": False, "error": e.message, "code": e.code,
                    "http_status": e.http_status}
    return wrapper


# --------------------------------------------------------------------------
# tools (plain functions; registered in build_server)
# --------------------------------------------------------------------------
@_safe
def auth_status() -> dict:
    """Whether an ICA account session is present. Run `ica login` in a terminal if not."""
    st = State.load()
    return {
        "logged_in": bool(st.access_token),
        "username": st.username,
        "registered_client": bool(st.client_id),
        "handla_cookie": bool(st.handla_cookie),
        "handla_store_id": st.handla_store_id,
    }


@_safe
def list_shopping_lists() -> list:
    """List all of the user's shopping lists (id, title, row count)."""
    return [{"id": s.get("id"), "title": s.get("title"),
             "rows": len(s.get("rows") or [])} for s in _api().lists()]


@_safe
def show_list(list: Optional[str] = None) -> dict:
    """Show one shopping list with its rows. `list` is an id or title (default: first)."""
    return _api().list_show(list)


@_safe
def create_list(title: str) -> dict:
    """Create a new shopping list with the given title."""
    return _api().create_list(title)


@_safe
def delete_list(list: str) -> dict:
    """Delete a shopping list (by id or title)."""
    sl = _api().list_show(list)
    _api().delete_list(sl["id"])
    return {"deleted": sl.get("id"), "title": sl.get("title")}


@_safe
def add_item(line: str, list: Optional[str] = None) -> dict:
    """Add an item to a list. `line` is free text like '2 st mjölk'. `list`=id/title (default first)."""
    return _api().add_item(list, line)


@_safe
def edit_item(item: str, list: Optional[str] = None, name: Optional[str] = None,
              quantity: Optional[float] = None, unit: Optional[str] = None,
              checked: Optional[bool] = None) -> dict:
    """Edit an item (matched by name or offlineId). Only provided fields change."""
    return _api().edit_item(list, item, name=name, quantity=quantity,
                            unit=unit, checked=checked)


@_safe
def check_item(item: str, list: Optional[str] = None) -> dict:
    """Mark an item as bought (strikethrough)."""
    return _api().edit_item(list, item, checked=True)


@_safe
def uncheck_item(item: str, list: Optional[str] = None) -> dict:
    """Un-mark a bought item."""
    return _api().edit_item(list, item, checked=False)


@_safe
def remove_item(item: str, list: Optional[str] = None) -> dict:
    """Remove an item from a list (matched by name or offlineId)."""
    return _api().remove_item(list, item)


@_safe
def most_purchased() -> Any:
    """The user's most purchased items (good for suggestions)."""
    return _api().most_purchased()


@_safe
def common_articles(list: Optional[str] = None) -> Any:
    """Common articles, optionally scoped to a list."""
    return _api().common_articles(list)


@_safe
def get_recipe(recipe_id: str) -> Any:
    """Fetch a recipe by its numeric id."""
    return _api().recipe(recipe_id)


@_safe
def search_recipes(query: str) -> Any:
    """Free-text recipe search."""
    return _api().recipe_search(query)


@_safe
def random_recipes() -> Any:
    """A set of random recipes."""
    return _api().recipe_random()


@_safe
def list_stores() -> Any:
    """List ICA stores."""
    return _api().stores()


@_safe
def store_offers(store_id: str) -> Any:
    """Current discounts/offers for a store id."""
    return _api().offers(store_id)


@_safe
def product_lookup(upc: str) -> Any:
    """Look up a product by EAN/UPC barcode (mobile API)."""
    return _api().product(upc)


@_safe
def bonus() -> Any:
    """Current loyalty bonus."""
    return _api().bonus()


# -- Handla online shop -----------------------------------------------------
@_safe
def handla_product_search(query: str, store_id: Optional[str] = None,
                          raw: bool = False) -> Any:
    """Search Handla products in a store (anonymous). Returns compact rows unless raw."""
    client = _handla(store_id, need_cookie=False)
    data = client.search(query)
    return data if raw else client.compact_search(data)


@_safe
def handla_cart_show(store_id: Optional[str] = None) -> Any:
    """Show the active Handla online cart (needs `ica handla login`)."""
    return _handla(store_id, need_cookie=True).get_cart()


@_safe
def handla_cart_add(product_id: str, delta: int = 1,
                    store_id: Optional[str] = None) -> Any:
    """Add/increase a product in the Handla cart by `delta` (default +1)."""
    return _handla(store_id, need_cookie=True).cart_add(product_id, delta)


@_safe
def handla_cart_remove(product_id: str, delta: int = 1,
                       store_id: Optional[str] = None) -> Any:
    """Decrease a product in the Handla cart by `delta` (line drops at 0)."""
    return _handla(store_id, need_cookie=True).cart_remove(product_id, delta)


TOOLS: list[Callable] = [
    auth_status,
    list_shopping_lists, show_list, create_list, delete_list,
    add_item, edit_item, check_item, uncheck_item, remove_item,
    most_purchased, common_articles,
    get_recipe, search_recipes, random_recipes,
    list_stores, store_offers, product_lookup, bonus,
    handla_product_search, handla_cart_show, handla_cart_add, handla_cart_remove,
]


# --------------------------------------------------------------------------
# server
# --------------------------------------------------------------------------
def build_server():
    """Construct the MCP server. Imports the optional `mcp` SDK (v1 or v2)."""
    try:  # SDK v2
        from mcp.server import MCPServer as Server  # type: ignore
    except ImportError:
        try:  # SDK v1
            from mcp.server.fastmcp import FastMCP as Server  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise SystemExit(
                "The MCP SDK is not installed. Install it with:\n"
                "  pip install '.[mcp]'   (or: pip install mcp)\n"
                "then run `ica-handla-mcp`."
            ) from e
    server = Server("ica-handla")
    for fn in TOOLS:
        server.tool()(fn)
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
