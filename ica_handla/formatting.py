"""Output rendering: JSON-first for agents, optional human text."""
from __future__ import annotations

import json
import sys
from typing import Any

from .errors import success_payload


def emit(data: Any, fmt: str = "json", text_fn=None) -> None:
    """Print a successful result.

    json (default): one line ``{"ok": true, "data": ...}`` on stdout.
    text:           human output via ``text_fn(data)`` if given, else a dump.
    """
    if fmt == "text" and text_fn is not None:
        out = text_fn(data)
        if out:
            sys.stdout.write(out if out.endswith("\n") else out + "\n")
        return
    sys.stdout.write(json.dumps(success_payload(data), ensure_ascii=False) + "\n")


# -- text renderers ---------------------------------------------------------
def lists_text(lists: list[dict]) -> str:
    if not lists:
        return "(no lists)"
    return "\n".join(
        f"{sl.get('id')}\t{sl.get('title')}\t({len(sl.get('rows') or [])} rows)"
        for sl in lists
    )


def list_show_text(sl: dict) -> str:
    head = f"# {sl.get('title')}  (id {sl.get('id')})"
    rows = sl.get("rows") or []
    if not rows:
        return head + "\n(empty)"
    lines = [head]
    for r in rows:
        mark = "x" if r.get("isStrikedOver") else " "
        qty = r.get("quantity")
        unit = r.get("unit") or ""
        qtxt = f"{qty:g} {unit} ".strip() + " " if qty else ""
        lines.append(f"[{mark}] {qtxt}{r.get('productName')}  ({r.get('offlineId')})")
    return "\n".join(lines)


def message_text(d: dict) -> str:
    return d.get("message") or json.dumps(d, ensure_ascii=False)
