"""`ica` command-line interface. JSON-first; see CLI.md for the full reference."""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from typing import Any

from . import formatting as fmtmod
from . import handla
from .api import IcaApi
from .auth import Authenticator
from .config import State, state_path
from .errors import AuthError, IcaError, UsageError, print_json_error

SUPPRESS = argparse.SUPPRESS


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", default=SUPPRESS,
                        help="debug logging on stderr")
    common.add_argument("-f", "--format", choices=["json", "text"], default=SUPPRESS,
                        help="output format (default json)")

    p = argparse.ArgumentParser(
        prog="ica", parents=[common],
        description="Unofficial ICA Handla CLI (shopping lists, recipes, offers, "
                    "stores, products). JSON-first output.",
    )
    g = p.add_subparsers(dest="group", required=True, metavar="<command>")

    def leaf(name, help):
        return g.add_parser(name, help=help, parents=[common])

    # auth / account
    lp = leaf("login", "register a device + log in with personnummer/password")
    lp.add_argument("-u", "--user", help="personnummer (or env ICA_USER)")
    lp.add_argument("-p", "--password", help="password (or env ICA_PASS; prompts if omitted)")
    leaf("logout", "revoke + clear saved tokens")
    leaf("refresh", "refresh the access token")
    leaf("register", "dynamic client registration only (no login)")
    leaf("whoami", "show the signed-in customer")
    tp = leaf("token", "import a captured token instead of logging in")
    tp.add_argument("--access-token")
    tp.add_argument("--refresh-token")

    # lists
    lg = leaf("lists", "manage shopping lists").add_subparsers(dest="cmd", required=True, metavar="<sub>")
    lg.add_parser("ls", help="list all lists", parents=[common])
    sp = lg.add_parser("show", help="show one list with rows", parents=[common])
    sp.add_argument("list", nargs="?", help="list id or title (default: first)")
    cp = lg.add_parser("create", help="create a new list", parents=[common])
    cp.add_argument("title")
    dp = lg.add_parser("delete", help="delete a list", parents=[common])
    dp.add_argument("list", help="list id or title")

    # items
    ig = leaf("item", "add/edit/remove items").add_subparsers(dest="cmd", required=True, metavar="<sub>")
    ap = ig.add_parser("add", help="add an item, e.g. '2 st mjölk'", parents=[common])
    ap.add_argument("line")
    ap.add_argument("--list", dest="list", help="list id or title (default: first)")
    ep = ig.add_parser("edit", help="change an item (match by name/offlineId)", parents=[common])
    ep.add_argument("item")
    ep.add_argument("--list", dest="list")
    ep.add_argument("--name")
    ep.add_argument("--qty", type=float)
    ep.add_argument("--unit")
    eg = ep.add_mutually_exclusive_group()
    eg.add_argument("--check", dest="checked", action="store_true", default=None)
    eg.add_argument("--uncheck", dest="checked", action="store_false", default=None)
    for sub in ("check", "uncheck", "remove"):
        q = ig.add_parser(sub, help=f"{sub} an item", parents=[common])
        q.add_argument("item")
        q.add_argument("--list", dest="list")

    # suggest
    sg = leaf("suggest", "common / most-purchased / suggested items").add_subparsers(
        dest="cmd", required=True, metavar="<sub>")
    cm = sg.add_parser("common", help="common articles (optionally for a list)", parents=[common])
    cm.add_argument("--list", dest="list")
    sg.add_parser("most-purchased", help="most purchased items", parents=[common])
    sg.add_parser("lists", help="suggested lists", parents=[common])

    # recipe
    rg = leaf("recipe", "recipes").add_subparsers(dest="cmd", required=True, metavar="<sub>")
    rget = rg.add_parser("get", help="get a recipe by id", parents=[common])
    rget.add_argument("id")
    rg.add_parser("random", help="random recipes", parents=[common])
    rg.add_parser("categories", help="recipe categories", parents=[common])
    rg.add_parser("favorites", help="favorite recipes", parents=[common])
    rs = rg.add_parser("search", help="search recipes", parents=[common])
    rs.add_argument("query")

    # stores / offers / product / bonus
    stg = leaf("stores", "stores").add_subparsers(dest="cmd", required=True, metavar="<sub>")
    stg.add_parser("ls", help="list stores", parents=[common])
    stg.add_parser("favorites", help="favorite stores", parents=[common])
    stget = stg.add_parser("get", help="store by id", parents=[common])
    stget.add_argument("id")

    op = leaf("offers", "discounts for a store")
    op.add_argument("store_id")

    bg = leaf("bonus", "loyalty bonus").add_subparsers(dest="cmd", required=True, metavar="<sub>")
    bg.add_parser("current", help="current bonus", parents=[common])
    bg.add_parser("transactions", help="bonus transactions", parents=[common])

    # --- Handla online shop (handlaprivatkund.ica.se: cookie + CSRF) -------
    hg = leaf("handla", "Handla web session (cookie)").add_subparsers(
        dest="cmd", required=True, metavar="<sub>")
    hl = hg.add_parser("login", help="save a Handla web session (cookie or browser)", parents=[common])
    hlg = hl.add_mutually_exclusive_group(required=True)
    hlg.add_argument("--cookie", help="raw Cookie header from browser DevTools")
    hlg.add_argument("--browser", action="store_true",
                     help="open a browser to log in and capture the cookie (needs Playwright)")
    hl.add_argument("--store-id", dest="store_id", help="default store id to remember")
    hg.add_parser("status", help="show saved Handla session state", parents=[common])
    hg.add_parser("logout", help="clear saved Handla cookie/store/csrf", parents=[common])

    pg = leaf("product", "Handla product search").add_subparsers(
        dest="cmd", required=True, metavar="<sub>")
    ps = pg.add_parser("search", help="search products in a store", parents=[common])
    ps.add_argument("query")
    ps.add_argument("--store-id", dest="store_id")
    ps.add_argument("--raw", action="store_true", help="full payload instead of compact")
    pl = pg.add_parser("lookup", help="look up a product by EAN/UPC (mobile API)", parents=[common])
    pl.add_argument("upc")

    cg = leaf("cart", "Handla online cart").add_subparsers(
        dest="cmd", required=True, metavar="<sub>")
    cs = cg.add_parser("show", help="show the active cart", parents=[common])
    cs.add_argument("--store-id", dest="store_id")
    ca = cg.add_parser("add", help="add/increase a product in the cart", parents=[common])
    ca.add_argument("product_id")
    ca.add_argument("-d", "--delta", type=int, default=1, help="quantity delta (default +1)")
    ca.add_argument("--store-id", dest="store_id")
    cr = cg.add_parser("remove", help="decrease a product (removes line at 0)", parents=[common])
    cr.add_argument("product_id")
    cr.add_argument("-d", "--delta", type=int, default=1, help="amount to decrease (default 1)")
    cr.add_argument("--store-id", dest="store_id")

    return p


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _creds(args) -> tuple[str, str]:
    user = getattr(args, "user", None) or os.environ.get("ICA_USER")
    if not user:
        user = input("Personnummer: ").strip()
    pw = getattr(args, "password", None) or os.environ.get("ICA_PASS")
    if not pw:
        pw = getpass.getpass("Password: ")
    return user, pw


def _api() -> IcaApi:
    return IcaApi(Authenticator(State.load()))


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------
def _dispatch(args) -> tuple[Any, Any]:
    """Return (data, text_fn) for the chosen command."""
    group = args.group
    cmd = getattr(args, "cmd", None)

    if group == "login":
        auth = Authenticator(State.load())
        user, pw = _creds(args)
        auth.login(user, pw)
        return {"message": f"logged in as {user}", "state": str(state_path())}, fmtmod.message_text

    if group == "token":
        st = State.load()
        if args.access_token:
            st.access_token = args.access_token
        if args.refresh_token:
            st.refresh_token = args.refresh_token
        if not (args.access_token or args.refresh_token):
            raise UsageError("pass --access-token and/or --refresh-token", code="usage")
        st.save()
        return {"message": "token stored", "state": str(state_path())}, fmtmod.message_text

    if group == "register":
        auth = Authenticator(State.load())
        auth.register_client(force=True)
        return {"client_id": auth.state.client_id, "scope": auth.state.client_scope}, None

    if group == "refresh":
        auth = Authenticator(State.load())
        auth.refresh()
        return {"message": "token refreshed"}, fmtmod.message_text

    if group == "logout":
        st = State.load()
        try:
            Authenticator(st).revoke()
        except Exception:  # noqa: BLE001
            pass
        st.clear()
        return {"message": "logged out"}, fmtmod.message_text

    if group == "whoami":
        return _api().customer(), None

    if group == "lists":
        api = _api()
        if cmd == "ls":
            return api.lists(), fmtmod.lists_text
        if cmd == "show":
            return api.list_show(args.list), fmtmod.list_show_text
        if cmd == "create":
            return api.create_list(args.title), None
        if cmd == "delete":
            sl = api.list_show(args.list)
            api.delete_list(sl["id"])
            return {"message": f"deleted list {sl['id']} ({sl.get('title')})"}, fmtmod.message_text

    if group == "item":
        api = _api()
        if cmd == "add":
            return api.add_item(args.list, args.line), None
        if cmd == "edit":
            return api.edit_item(args.list, args.item, name=args.name, quantity=args.qty,
                                 unit=args.unit, checked=args.checked), None
        if cmd == "remove":
            return api.remove_item(args.list, args.item), None
        if cmd in ("check", "uncheck"):
            return api.edit_item(args.list, args.item, checked=(cmd == "check")), None

    if group == "suggest":
        api = _api()
        if cmd == "common":
            return api.common_articles(args.list), None
        if cmd == "most-purchased":
            return api.most_purchased(), None
        if cmd == "lists":
            return api.suggestions(), None

    if group == "recipe":
        api = _api()
        if cmd == "get":
            return api.recipe(args.id), None
        if cmd == "random":
            return api.recipe_random(), None
        if cmd == "categories":
            return api.recipe_categories(), None
        if cmd == "favorites":
            return api.recipe_favorites(), None
        if cmd == "search":
            return api.recipe_search(args.query), None

    if group == "stores":
        api = _api()
        if cmd == "ls":
            return api.stores(), None
        if cmd == "favorites":
            return api.store_favorites(), None
        if cmd == "get":
            return api.store(args.id), None

    if group == "offers":
        return _api().offers(args.store_id), None

    if group == "bonus":
        api = _api()
        return (api.bonus() if cmd == "current" else api.bonus_transactions()), None

    # --- Handla online shop -----------------------------------------------
    if group == "handla":
        st = State.load()
        if cmd == "login":
            if getattr(args, "browser", False):
                from . import browser_login
                store_id = handla.resolve_store_id(st, args.store_id)
                cookie = browser_login.capture_cookie(store_id)
                st.handla_store_id = store_id
            else:
                cookie = args.cookie.strip()
                if args.store_id:
                    st.handla_store_id = args.store_id.strip()
            st.handla_cookie = cookie
            st.handla_csrf = None  # force re-fetch on next mutation
            st.save()
            return {"message": "Handla web session saved",
                    "store_id": st.handla_store_id}, fmtmod.message_text
        if cmd == "status":
            return {"has_cookie": bool(st.handla_cookie),
                    "store_id": st.handla_store_id,
                    "has_csrf": bool(st.handla_csrf)}, None
        if cmd == "logout":
            st.handla_cookie = st.handla_store_id = st.handla_csrf = None
            st.save()
            return {"message": "Handla web session cleared"}, fmtmod.message_text

    if group == "product":
        if cmd == "lookup":
            return _api().product(args.upc), None
        if cmd == "search":
            st = State.load()
            store_id = handla.resolve_store_id(st, args.store_id)
            client = handla.HandlaClient(store_id, state=st)
            data = client.search(args.query)
            return (data if args.raw else client.compact_search(data)), None

    if group == "cart":
        st = State.load()
        store_id = handla.resolve_store_id(st, args.store_id)
        cookie = handla.resolve_cookie(st)
        client = handla.HandlaClient(store_id, cookie_header=cookie, state=st)
        if cmd == "show":
            return client.get_cart(), None
        if cmd == "add":
            return client.cart_add(args.product_id, args.delta), None
        if cmd == "remove":
            return client.cart_remove(args.product_id, args.delta), None

    raise UsageError(f"unknown command {group!r}", code="usage")


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fmt = getattr(args, "format", "json")
    if getattr(args, "verbose", False):
        logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                            format="[%(name)s] %(message)s")
    try:
        data, text_fn = _dispatch(args)
    except IcaError as e:
        print_json_error(e)
        return e.exit_code
    except KeyboardInterrupt:
        print_json_error(AuthError("interrupted", code="interrupted"))
        return 1
    fmtmod.emit(data, fmt, text_fn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
