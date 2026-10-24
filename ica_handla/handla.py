"""Handla Online storefront: anonymous product search + cart (cookie + CSRF).

This is a DIFFERENT backend from the mobile app API: the web shop at
``handlaprivatkund.ica.se``. It is not part of the decompiled APK; the endpoint
shapes here follow the public Handla web client (and mirror the approach in
mar-schmidt/ica-cli). Auth is a browser **session cookie** plus a per-session
**CSRF token** scraped from the store page; product search is anonymous.

Everything is scoped to a numeric ``store_id`` (from a Handla store URL).
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlencode

import requests

from . import http
from .config import State, config_dir  # noqa: F401  (config_dir kept for parity)
from .errors import AuthError, UpstreamError, UsageError

_LOG = logging.getLogger("ica_handla.handla")

HANDLA_HOST = "https://handlaprivatkund.ica.se"
_COOKIE_DOMAIN = ".handlaprivatkund.ica.se"

# Handla's WAF 403s the default python-requests UA; present as a browser.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
_CSRF_RE = re.compile(
    r'"csrf"\s*:\s*\{\s*"token"\s*:\s*"'
    r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"',
    re.IGNORECASE,
)


def resolve_store_id(state: State, explicit: str | None) -> str:
    import os
    sid = (explicit or os.environ.get("ICA_HANDLA_STORE_ID") or state.handla_store_id or "").strip()
    if not sid:
        raise UsageError("no Handla store id; pass --store-id or set ICA_HANDLA_STORE_ID "
                         "(or `ica handla login --store-id N`)", code="missing_handla_store_id")
    return sid


def resolve_cookie(state: State, explicit: str | None = None) -> str:
    import os
    cookie = (explicit or os.environ.get("ICA_HANDLA_COOKIE") or state.handla_cookie or "").strip()
    if not cookie:
        raise AuthError("no Handla web session; capture the Cookie header from your "
                        "browser and run `ica handla login --cookie '<header>'`",
                        code="missing_handla_web_session")
    return cookie


def _store_base(store_id: str) -> str:
    return f"{HANDLA_HOST}/stores/{store_id.strip().rstrip('/')}/"


def _apply_cookie(session: requests.Session, cookie_header: str) -> None:
    session.cookies.clear()
    for part in cookie_header.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        session.cookies.set(name.strip(), value.strip(), domain=_COOKIE_DOMAIN, path="/")


class HandlaClient:
    def __init__(self, store_id: str, *, cookie_header: str | None = None,
                 state: State | None = None):
        self.store_id = store_id.strip()
        self.base = _store_base(self.store_id)
        self.state = state
        self.session = http.make_session()
        self.session.headers.update({"User-Agent": _BROWSER_UA, "Accept": "application/json"})
        if cookie_header:
            _apply_cookie(self.session, cookie_header)

    def _url(self, path: str) -> str:
        return self.base + path.lstrip("/")

    # -- anonymous product search ------------------------------------------
    def search(self, query: str, *, page_size: int = 50, decorate: int = 50) -> Any:
        params = {
            "q": query,
            "includeAdditionalPageInfo": "true",
            "maxPageSize": str(page_size),
            "maxProductsToDecorate": str(decorate),
            "tag": "web",
        }
        url = self._url("api/webproductpagews/v6/product-pages/search?" + urlencode(params))
        headers = {
            "Accept": "application/json",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
            "Referer": self.base,
            "User-Agent": _BROWSER_UA,
        }
        resp = http.request(self.session, "GET", url, headers=headers,
                            retry_202=True, max_wait=120.0)
        return http.json_or_raise(resp, context="handla search")

    @staticmethod
    def compact_search(data: Any) -> list[dict]:
        """Trim a search payload to agent-friendly {name, productId, unit?}."""
        items: list[dict] = []
        entities = []
        if isinstance(data, dict):
            # Handla nests products under products/entities/items depending on version.
            for key in ("products", "entities", "items", "results"):
                v = data.get(key)
                if isinstance(v, list):
                    entities = v
                    break
            if not entities:
                prods = (data.get("productPage") or {}).get("products")
                if isinstance(prods, list):
                    entities = prods
        for p in entities:
            if not isinstance(p, dict):
                continue
            row = {
                "name": p.get("name") or p.get("title"),
                "productId": p.get("productId") or p.get("id") or p.get("retailProductId"),
            }
            uom = p.get("unitOfMeasure") or p.get("unit")
            if uom:
                row["unitOfMeasure"] = uom
            if row["productId"]:
                items.append(row)
        return items

    # -- cart (needs cookie + CSRF) ----------------------------------------
    def _csrf(self, *, force: bool = False) -> str:
        if not force and self.state and self.state.handla_csrf:
            return self.state.handla_csrf
        resp = http.request(self.session, "GET", self.base, headers={
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        })
        if resp.status_code >= 400:
            raise UpstreamError(f"could not load Handla store page (HTTP {resp.status_code}); "
                                "cookie may be expired", code="handla_csrf_failed",
                                http_status=resp.status_code)
        m = _CSRF_RE.search(resp.text)
        if not m:
            raise UpstreamError("could not find CSRF token in Handla store page "
                                "(cookie invalid or layout changed)", code="handla_csrf_failed")
        token = m.group(1)
        if self.state is not None:
            self.state.handla_csrf = token
            self.state.save()
        return token

    def get_cart(self) -> Any:
        resp = http.request(self.session, "GET", self._url("api/cart/v1/carts/active"))
        return http.json_or_raise(resp, context="handla cart")

    def apply_quantity(self, updates: list[dict]) -> Any:
        url = self._url("api/cart/v1/carts/active/apply-quantity")
        for attempt in range(2):
            csrf = self._csrf(force=(attempt == 1))
            headers = {
                "Origin": HANDLA_HOST,
                "Referer": self.base,
                "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
                "Content-Type": "application/json",
                "X-CSRF-TOKEN": csrf,
            }
            resp = http.request(self.session, "POST", url, headers=headers, json=updates)
            if resp.status_code == 403 and attempt == 0:
                _LOG.info("cart mutation 403, refreshing CSRF and retrying")
                continue
            return http.json_or_raise(resp, context="handla cart mutation")

    def cart_add(self, product_id: str, delta: int = 1) -> Any:
        return self.apply_quantity([{"productId": product_id.strip(), "quantity": int(delta)}])

    def cart_remove(self, product_id: str, delta: int = 1) -> Any:
        return self.apply_quantity([{"productId": product_id.strip(), "quantity": -abs(int(delta))}])
