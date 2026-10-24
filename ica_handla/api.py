"""High-level ICA Handla API client covering the app's service endpoints."""
from __future__ import annotations

import uuid
from typing import Any

from . import const, http, models
from .auth import Authenticator
from .errors import AuthError


class IcaApi:
    def __init__(self, auth: Authenticator):
        self.auth = auth
        self.session = auth.session

    # -- request plumbing --------------------------------------------------
    def _call(self, method: str, path: str, *, retry_202: bool = False,
              **kwargs: Any) -> Any:
        url = const.API_BASE + path
        headers = {"Authorization": f"Bearer {self.auth.bearer()}"}
        resp = http.request(self.session, method, url, headers=headers,
                            retry_202=retry_202, **kwargs)
        if resp.status_code == 401 and self.auth.state.refresh_token:
            self.auth.refresh()
            headers = {"Authorization": f"Bearer {self.auth.bearer()}"}
            resp = http.request(self.session, method, url, headers=headers,
                                retry_202=retry_202, **kwargs)
        return http.json_or_raise(resp, context=path)

    def _get(self, path: str, **kw: Any) -> Any:
        return self._call("GET", path, **kw)

    def _post(self, path: str, payload: Any = None, **kw: Any) -> Any:
        return self._call("POST", path, json=payload, **kw)

    def _delete(self, path: str, **kw: Any) -> Any:
        return self._call("DELETE", path, **kw)

    # -- shopping lists ----------------------------------------------------
    def lists(self) -> list[dict]:
        return self._get(const.EP_LISTS).get("shoppingLists", [])

    def list_show(self, selector: str | None) -> dict:
        return models.resolve_list(self.lists(), selector)

    def create_list(self, title: str) -> dict:
        body = {
            "offlineId": uuid.uuid4().hex,
            "title": title,
            "commentText": None,
            "sortingStore": 0,
            "rows": [],
            "latestChange": models.now_iso(),
        }
        return self._post(const.EP_LISTS, body)

    def delete_list(self, list_id) -> Any:
        # The gateway wants offlineIds here (numeric ids give a 400).
        sl = self.list_show(str(list_id))
        return self._post(const.EP_LISTS_DELETE, [sl["offlineId"]])

    def _sync(self, sl: dict, **kw) -> Any:
        # The gateway addresses lists by offlineId in the path (numeric ids 500).
        return self._post(const.EP_LIST_SYNC.format(id=sl["offlineId"]), models.sync_body(**kw))

    def add_item(self, selector: str | None, line: str) -> dict:
        sl = self.list_show(selector)
        parsed = models.parse_line(line)
        row = models.new_row(parsed["productName"], quantity=parsed.get("quantity"),
                             unit=parsed.get("unit"),
                             article_group_id=const.DEFAULT_ARTICLE_GROUP_ID)
        result = self._sync(sl, created=[row])
        return {"list": _list_brief(sl), "added": row, "result": result}

    def edit_item(self, selector, query, *, name=None, quantity=None, unit=None,
                  checked=None) -> dict:
        sl = self.list_show(selector)
        src = models.find_row(sl, query)
        row = models.new_row(
            name if name is not None else src.get("productName"),
            quantity=quantity if quantity is not None else src.get("quantity"),
            unit=unit if unit is not None else src.get("unit"),
            checked=checked if checked is not None else bool(src.get("isStrikedOver")),
            internal_order=src.get("internalOrder", 0),
            offline_id=src["offlineId"],
        )
        result = self._sync(sl, changed=[row])
        return {"list": _list_brief(sl), "row": src, "result": result}

    def remove_item(self, selector, query) -> dict:
        sl = self.list_show(selector)
        src = models.find_row(sl, query)
        result = self._sync(sl, deleted=[src["offlineId"]])
        return {"list": _list_brief(sl), "row": src, "result": result}

    # suggestions / common articles
    def most_purchased(self) -> Any:
        return self._get(const.EP_MOST_PURCHASED)

    def common_articles(self, selector: str | None = None) -> Any:
        if selector is None:
            return self._get(const.EP_COMMON)
        sl = self.list_show(selector)
        return self._get(const.EP_LIST_COMMON.format(id=sl["id"]))

    def suggestions(self) -> Any:
        return self._get(const.EP_SUGGESTIONS)

    def baseitems(self) -> Any:
        return self._get(const.EP_BASEITEMS)

    # -- recipes -----------------------------------------------------------
    def recipe(self, recipe_id) -> Any:
        return self._get(const.EP_RECIPE.format(id=recipe_id))

    def recipe_random(self) -> Any:
        return self._get(const.EP_RECIPE_RANDOM)

    def recipe_categories(self) -> Any:
        return self._get(const.EP_RECIPE_CATEGORIES)

    def recipe_favorites(self) -> Any:
        return self._get(const.EP_RECIPE_FAVORITES)

    def recipe_search(self, query: str, *, page: int = 1, per_page: int = 20,
                      **extra: Any) -> Any:
        # GET only (POST -> 405). The term goes in ``phrase``; ``freeText`` is
        # silently ignored and returns every recipe.
        params = {"phrase": query, "pageNumber": page, "recordsPerPage": per_page,
                  "api-version": 2, **extra}
        return self._get(const.EP_RECIPE_SEARCH, params=params, retry_202=True)

    # -- offers / stores / product / bonus ---------------------------------
    def offers(self, store_id) -> Any:
        return self._get(const.EP_OFFERS.format(storeId=store_id))

    def offers_search(self, offer_ids: list, store_ids: list) -> Any:
        """Details for specific offers at specific stores (app: ``offerSearch``).

        Returns ``{"storeOffers": [{"storeId", "offers": [...]}]}``. Without
        ``api-version=2`` the server returns an older, differently shaped list.
        """
        body = {"offerIds": [str(i) for i in offer_ids],
                "storeIds": [int(i) for i in store_ids]}
        return self._post(const.EP_OFFERS_SEARCH, body, params={"api-version": 2},
                          retry_202=True)

    def user_discounts(self, store_ids: list) -> Any:
        """Personal discounts for the given stores (app: ``fetchUserDiscounts``)."""
        return self._post(const.EP_USER_DISCOUNTS, {"storeIds": [int(i) for i in store_ids]},
                          params={"api-version": 2})

    def stores(self) -> Any:
        return self._get(const.EP_STORES)

    def store(self, store_id) -> Any:
        return self._get(const.EP_STORE.format(id=store_id))

    def store_favorites(self) -> Any:
        return self._get(const.EP_STORE_FAVORITES)

    def product(self, upc: str) -> Any:
        return self._get(const.EP_PRODUCT.format(upc=upc))

    def bonus(self) -> Any:
        return self._get(const.EP_BONUS_CURRENT)

    def bonus_transactions(self) -> Any:
        return self._get(const.EP_BONUS_TRANSACTIONS)

    # -- account -----------------------------------------------------------
    def customer(self) -> Any:
        return self._get(const.EP_CUSTOMER)

    def preferences(self) -> Any:
        return self._get(const.EP_CUSTOMER_PREFERENCES)


def _list_brief(sl: dict) -> dict:
    return {"id": sl.get("id"), "offlineId": sl.get("offlineId"), "title": sl.get("title")}
