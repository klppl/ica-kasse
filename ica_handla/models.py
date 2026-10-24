"""Domain helpers: free-text line parsing, sync-row builders, resolution."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from . import const
from .errors import NotFoundError, UsageError

# "2 st mjölk" / "mjölk" / "1,5 l mellanmjölk"  (unit list from the app)
_LINE_RE = re.compile(
    r"^\s*(?:(?P<quantity>[0-9]+(?:[.,][0-9]+)?)\s+)?"
    r"(?:(?P<unit>" + "|".join(const.UNITS) + r")\s+)?"
    r"(?P<name>.+?)\s*$",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime(const.DATE_FMT)


def parse_line(line: str) -> dict[str, Any]:
    """Parse '2 st mjölk' -> {productName, quantity?, unit?}."""
    m = _LINE_RE.match(line)
    if not m or not (m.group("name") or "").strip():
        return {"productName": line.strip()}
    out: dict[str, Any] = {"productName": m.group("name").strip()}
    if m.group("quantity"):
        out["quantity"] = float(m.group("quantity").replace(",", "."))
    if m.group("unit"):
        out["unit"] = m.group("unit").lower()
    return out


def new_row(product_name: str, *, quantity: float | None = None,
            unit: str | None = None, checked: bool = False,
            internal_order: int = 0,
            article_group_id: int | None = None,
            offline_id: str | None = None) -> dict[str, Any]:
    """Build a SyncBody.Row (createdRows/changedRows). latestChange+offlineId required."""
    return {
        "productName": product_name,
        "quantity": quantity,
        "unit": unit,
        "isStrikedOver": checked,
        "internalOrder": internal_order,
        "articleGroupId": article_group_id,
        "latestChange": now_iso(),
        "offlineId": offline_id or str(uuid.uuid4()),
    }


def sync_body(*, created=None, changed=None, deleted=None,
              title: str | None = None) -> dict[str, Any]:
    ts = now_iso()
    return {
        "changedShoppingListProperties": {
            "sortingStore": None, "title": title,
            "commentText": None, "latestChange": ts,
        },
        "createdRows": created or [],
        "changedRows": changed or [],
        "deletedRows": deleted or [],
    }


def resolve_list(lists: list[dict], selector: str | None) -> dict:
    """Pick a list by numeric id, exact/substring title, or first if None."""
    if not lists:
        raise NotFoundError("no shopping lists found; create one first", code="no_lists")
    if selector is None:
        return lists[0]
    sel = str(selector).strip()
    for sl in lists:
        if str(sl.get("id")) == sel or sl.get("offlineId") == sel:
            return sl
    low = sel.lower()
    exact = [s for s in lists if (s.get("title") or "").lower() == low]
    if len(exact) == 1:
        return exact[0]
    subs = [s for s in lists if low in (s.get("title") or "").lower()]
    if len(subs) == 1:
        return subs[0]
    cands = exact or subs
    if not cands:
        raise NotFoundError(f"no list matching {selector!r}", code="list_not_found")
    names = ", ".join(f"{s.get('id')}:{s.get('title')}" for s in cands)
    raise UsageError(f"{selector!r} is ambiguous; specify an id ({names})",
                     code="ambiguous_list")


def find_row(list_obj: dict, query: str) -> dict:
    """Find one row by offlineId, exact productName, or substring."""
    rows = list_obj.get("rows") or []
    for r in rows:
        if r.get("offlineId") == query:
            return r
    low = query.strip().lower()
    exact = [r for r in rows if (r.get("productName") or "").lower() == low]
    if len(exact) == 1:
        return exact[0]
    subs = [r for r in rows if low in (r.get("productName") or "").lower()]
    if len(subs) == 1:
        return subs[0]
    cands = exact or subs
    if not cands:
        raise NotFoundError(f"no item matching {query!r} in that list", code="row_not_found")
    names = ", ".join(r.get("productName") or "?" for r in cands)
    raise UsageError(f"{query!r} matches several items: {names}", code="ambiguous_row")
