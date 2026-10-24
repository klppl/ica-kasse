#!/usr/bin/env python3
"""
Unofficial ICA Handla ("inköpslista") API client.

Reverse-engineered from se.ica.handla 4.79.1. For personal interoperability use
with your own ICA account. Not affiliated with or endorsed by ICA.

Auth model (Curity OAuth2 + PKCE + Dynamic Client Registration):
  1. Bootstrap: POST /oauth/v2/token (client_credentials, scope=dcr) with the app's
     static DCR bootstrap client  ->  a one-off registration token.
  2. DCR: POST /register (Bearer <reg token>, body {"software_id": ...})
     ->  an ephemeral client_id / client_secret for this "device".
  3. Authorize: GET /oauth/v2/authorize?... (PKCE S256, acr = html-form password
     authenticator)  ->  Curity HTML login page.  Submit username (personnummer)
     + password  ->  302 redirect to icacurity://app?code=...
  4. Token: POST /oauth/v2/token (authorization_code, code_verifier)  ->  access +
     refresh token.
  5. API: apimgw-pub.ica.se/sverige/digx/mobile/ with  Authorization: Bearer <access token>.

Adding an item to a list is a POST to
  shoppinglistservice/v1/shoppinglists/{id}/sync
with the item in `createdRows`.

Credentials are NEVER hardcoded. Supply them via env vars (ICA_USER / ICA_PASS),
a prompt, or skip login entirely by passing a --refresh-token / --access-token you
captured from a real session.

State (DCR client + tokens) is cached in ~/.ica_handla.json, mirroring the app's
SharedPreferences, so you register + log in once and reuse the refresh token.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import sys
import time
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

# ---------------------------------------------------------------------------
# Constants recovered from the APK (se.ica.handla 4.79.1, PROD environment)
# ---------------------------------------------------------------------------
IMS_BASE = "https://ims.icagruppen.se/"            # NetworkModule.imsBaseUrl(PROD)
API_BASE = "https://apimgw-pub.ica.se/sverige/digx/mobile/"  # old handla.api.ica.se is gone

DCR_CLIENT_ID = "ica-app-dcr-registration"         # NetworkModule.DCR_CLIENT_ID
DCR_CLIENT_SECRET = "uxLHTBvZ-Z2fV-SbrHl1E-tz7vB3jQFrwAdSLlbVMMu1rxDdvJU0s8KGu9d1wLS4"  # DCR_CLIENT_SECRET_PROD
DCR_SOFTWARE_ID = "dcr-ica-app-template"           # Curity.DCR_SOFTWARE_ID
DCR_SCOPE = "dcr"                                   # Curity.DCR_SCOPE

# authorize/login scope (Curity.CLIENT_SCOPES). Token exchange uses the scope the
# DCR response hands back, which we store per client.
AUTH_SCOPE = "icaappen openid ica_app_stammis2"
REDIRECT_URI = "icacurity://app"                   # Curity.LOGIN_REDIRECT_URI
ACR_PASSWORD = "urn:se:curity:authentication:html-form:IcaCustomers"  # LoginMethod.Password
ACR_BANKID = "urn:se:curity:authentication:bankid:icase-bankid-qr"    # LoginMethod.BankId

APP_VERSION = "4.79.1"
ANDROID_RELEASE = "14"
USER_AGENT = f"ICA Appen {APP_VERSION} (Android {ANDROID_RELEASE})"

STATE_FILE = Path.home() / ".ica_handla.json"
DATE_FMT = "%Y-%m-%dT%H:%M:%SZ"                     # ServerDateFormat


def now_iso() -> str:
    """Timestamp in the format the server expects (UTC, ServerDateFormat)."""
    return datetime.now(timezone.utc).strftime(DATE_FMT)


# ---------------------------------------------------------------------------
# PKCE (CodeVerifier.kt: 32 random bytes, base64url no padding; S256 challenge)
# ---------------------------------------------------------------------------
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_code_verifier() -> str:
    return _b64url(secrets.token_bytes(32))


def code_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


# ---------------------------------------------------------------------------
# Minimal HTML <form> parser (so we don't need BeautifulSoup)
# ---------------------------------------------------------------------------
class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict] = []
        self._cur: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "form":
            self._cur = {"action": a.get("action", ""),
                         "method": a.get("method", "post").lower(),
                         "fields": {}, "field_types": {}}
            self.forms.append(self._cur)
        elif tag in ("input", "button") and self._cur is not None:
            name = a.get("name")
            if name:
                self._cur["fields"][name] = a.get("value", "")
                self._cur["field_types"][name] = a.get("type", "text").lower()

    def handle_endtag(self, tag):
        if tag == "form":
            self._cur = None


def parse_forms(html: str) -> list[dict]:
    p = _FormParser()
    p.feed(html)
    return p.forms


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class IcaClient:
    def __init__(self, verbose: bool = False):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "x-user-agent": USER_AGENT})
        self.verbose = verbose
        self.client_id: str | None = None
        self.client_secret: str | None = None
        self.client_scope: str | None = None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_scope: str | None = None
        self._load_state()

    # -- state cache --------------------------------------------------------
    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                d = json.loads(STATE_FILE.read_text())
                self.client_id = d.get("client_id")
                self.client_secret = d.get("client_secret")
                self.client_scope = d.get("client_scope")
                self.access_token = d.get("access_token")
                self.refresh_token = d.get("refresh_token")
                self.token_scope = d.get("token_scope")
            except Exception as e:  # noqa: BLE001
                self._log(f"could not read state file: {e}")

    def _save_state(self) -> None:
        d = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "client_scope": self.client_scope,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_scope": self.token_scope,
        }
        STATE_FILE.write_text(json.dumps(d, indent=2))
        try:
            STATE_FILE.chmod(0o600)
        except OSError:
            pass

    def _log(self, *a) -> None:
        if self.verbose:
            print("[ica]", *a, file=sys.stderr)

    def _corr_headers(self) -> dict:
        cid = str(uuid.uuid4())
        return {"X-Correlation-ID": cid, "X-Request-ID": cid}

    # -- step 1 + 2: DCR ----------------------------------------------------
    def register_client(self, force: bool = False) -> None:
        if self.client_id and not force:
            self._log("client already registered:", self.client_id)
            return
        # 1. bootstrap registration token
        r = self.s.post(
            IMS_BASE + "oauth/v2/token",
            data={
                "client_id": DCR_CLIENT_ID,
                "client_secret": DCR_CLIENT_SECRET,
                "grant_type": "client_credentials",
                "scope": DCR_SCOPE,
                "response_type": "token",
            },
            headers=self._corr_headers(),
            timeout=30,
        )
        self._log("bootstrap token status", r.status_code)
        r.raise_for_status()
        reg_token = r.json()["access_token"]

        # 2. dynamic client registration
        r = self.s.post(
            IMS_BASE + "register",
            headers={"Authorization": f"Bearer {reg_token}", **self._corr_headers()},
            json={"software_id": DCR_SOFTWARE_ID},
            timeout=30,
        )
        self._log("register status", r.status_code)
        r.raise_for_status()
        d = r.json()
        self.client_id = d["client_id"]
        self.client_secret = d["client_secret"]
        self.client_scope = d.get("scope", AUTH_SCOPE)
        self._save_state()
        self._log("registered client", self.client_id, "scope", self.client_scope)

    # -- step 3: interactive login (html-form authenticator) ----------------
    def login(self, username: str, password: str) -> None:
        """Drive Curity's HTML-form password authenticator to obtain a `code`."""
        if not self.client_id:
            self.register_client()

        verifier = new_code_verifier()
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": self.client_id,
            "scope": AUTH_SCOPE,
            "response_type": "code",
            "prompt": "login",
            "redirect_uri": REDIRECT_URI,
            "max_age": "0",
            "state": state,
            "nonce": secrets.token_urlsafe(16),
            "_cb": str(int(time.time() * 1000)),
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "acr": ACR_PASSWORD,
        }
        # Don't let requests swallow the custom-scheme redirect.
        r = self.s.get(IMS_BASE + "oauth/v2/authorize", params=params,
                       headers=self._corr_headers(), allow_redirects=True, timeout=30)
        self._log("authorize ->", r.status_code, r.url)

        code = self._submit_login_form(r, username, password)
        if not code:
            raise RuntimeError(
                "Login form flow did not yield an authorization code. "
                "Curity may require an extra step (BankID, consent, OTP) or the "
                "credentials were rejected. Run with -v and inspect, or use "
                "--refresh-token captured from a real session instead."
            )
        self._exchange_code(code, verifier)

    def _submit_login_form(self, resp: requests.Response, username: str,
                           password: str, max_steps: int = 6) -> str | None:
        """Walk the Curity login forms until we hit the redirect carrying ?code."""
        for step in range(max_steps):
            # Did a prior POST already redirect to the app scheme?
            code = self._code_from_history(resp)
            if code:
                return code

            forms = parse_forms(resp.text)
            if not forms:
                self._log("no form at step", step, "url", resp.url)
                return None

            form = self._pick_login_form(forms)
            data = dict(form["fields"])
            # Fill user / password fields by detected type/name.
            for name, ftype in form["field_types"].items():
                lname = name.lower()
                if ftype == "password" or "password" in lname:
                    data[name] = password
                elif lname in ("username", "username", "user", "userid",
                               "personalnumber", "ssn") or "user" in lname:
                    data[name] = username
            # Curity html-form defaults, in case nothing matched above.
            data.setdefault("userName", username)
            data.setdefault("password", password)

            action = requests.compat.urljoin(resp.url, form["action"] or resp.url)
            self._log(f"submitting form step {step} -> {action} fields={list(data)}")
            if form["method"] == "get":
                resp = self.s.get(action, params=data, headers=self._corr_headers(),
                                  allow_redirects=True, timeout=30)
            else:
                resp = self.s.post(action, data=data, headers=self._corr_headers(),
                                   allow_redirects=True, timeout=30)
            self._log("  ->", resp.status_code, resp.url)
        return self._code_from_history(resp)

    @staticmethod
    def _pick_login_form(forms: list[dict]) -> dict:
        for f in forms:
            if any(t == "password" or "password" in n.lower()
                   for n, t in f["field_types"].items()):
                return f
        return forms[0]

    def _code_from_history(self, resp: requests.Response) -> str | None:
        """requests aborts on icacurity:// — the target shows up as a failed
        redirect in history or in the response URL. Scan everything we saw."""
        candidates = [resp.url] + [h.headers.get("location", "") for h in resp.history]
        for u in candidates:
            if not u:
                continue
            pu = urlparse(u)
            if pu.scheme == "icacurity" or "code=" in u:
                qs = parse_qs(pu.query)
                if "code" in qs:
                    return qs["code"][0]
        return None

    # -- step 4: token exchange / refresh -----------------------------------
    def _exchange_code(self, code: str, verifier: str) -> None:
        r = self.s.post(
            IMS_BASE + "oauth/v2/token",
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "authorization_code",
                "scope": self.client_scope or AUTH_SCOPE,
                "response_type": "token",
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
            },
            headers=self._corr_headers(), timeout=30,
        )
        self._log("token exchange", r.status_code)
        r.raise_for_status()
        self._store_token(r.json())

    def refresh(self) -> None:
        if not self.refresh_token:
            raise RuntimeError("no refresh token; run `login` first")
        if not self.client_id:
            raise RuntimeError("no registered client; run `register` first")
        r = self.s.post(
            IMS_BASE + "oauth/v2/token",
            data={
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "scope": self.token_scope or self.client_scope or AUTH_SCOPE,
                "response_type": "token",
                "redirect_uri": REDIRECT_URI,
            },
            headers=self._corr_headers(), timeout=30,
        )
        self._log("refresh", r.status_code)
        r.raise_for_status()
        self._store_token(r.json())

    def _store_token(self, d: dict) -> None:
        self.access_token = d.get("access_token")
        self.refresh_token = d.get("refresh_token", self.refresh_token)
        self.token_scope = d.get("scope", self.token_scope)
        self._save_state()
        self._log("stored token, expires_in", d.get("expires_in"))

    # -- API calls ----------------------------------------------------------
    def _auth_headers(self) -> dict:
        if not self.access_token:
            raise RuntimeError("no access token; run `login` or `refresh` first")
        return {"Authorization": f"Bearer {self.access_token}", **self._corr_headers()}

    def _get(self, path: str) -> requests.Response:
        r = self.s.get(API_BASE + path, headers=self._auth_headers(), timeout=30)
        if r.status_code == 401 and self.refresh_token:
            self._log("401 -> refreshing token")
            self.refresh()
            r = self.s.get(API_BASE + path, headers=self._auth_headers(), timeout=30)
        r.raise_for_status()
        return r

    def _post(self, path: str, payload) -> requests.Response:
        r = self.s.post(API_BASE + path, json=payload,
                        headers=self._auth_headers(), timeout=30)
        if r.status_code == 401 and self.refresh_token:
            self._log("401 -> refreshing token")
            self.refresh()
            r = self.s.post(API_BASE + path, json=payload,
                           headers=self._auth_headers(), timeout=30)
        r.raise_for_status()
        return r

    def shopping_lists(self) -> list[dict]:
        return self._get("shoppinglistservice/v1/shoppinglists").json().get("shoppingLists", [])

    # -- list / row resolution ---------------------------------------------
    def resolve_list(self, selector) -> dict:
        """Find a list by numeric id or by (case-insensitive) title.

        `selector` may be None -> first list, an int/str id, or a title. Raises
        on no match or an ambiguous title match.
        """
        lists = self.shopping_lists()
        if not lists:
            raise RuntimeError("no shopping lists found; create one in the app first")
        if selector is None:
            return lists[0]
        sel = str(selector).strip()
        for sl in lists:                              # exact id
            if str(sl.get("id")) == sel:
                return sl
        low = sel.lower()                             # exact title, then substring
        exact = [sl for sl in lists if (sl.get("title") or "").lower() == low]
        if len(exact) == 1:
            return exact[0]
        subs = [sl for sl in lists if low in (sl.get("title") or "").lower()]
        if len(subs) == 1:
            return subs[0]
        if not exact and not subs:
            raise RuntimeError(f"no list matching {selector!r}")
        names = ", ".join(f"{s.get('id')}:{s.get('title')}" for s in (exact or subs))
        raise RuntimeError(f"{selector!r} is ambiguous; specify an id ({names})")

    @staticmethod
    def find_row(list_obj: dict, query: str) -> dict:
        """Find one row in a list by offlineId, exact productName, or substring."""
        rows = list_obj.get("rows") or []
        for r in rows:                                # exact offlineId
            if r.get("offlineId") == query:
                return r
        low = query.strip().lower()
        exact = [r for r in rows if (r.get("productName") or "").lower() == low]
        if len(exact) == 1:
            return exact[0]
        subs = [r for r in rows if low in (r.get("productName") or "").lower()]
        if len(subs) == 1:
            return subs[0]
        matches = exact or subs
        if not matches:
            raise RuntimeError(f"no item matching {query!r} in that list")
        names = ", ".join(f"{r.get('productName')}" for r in matches)
        raise RuntimeError(f"{query!r} matches several items: {names}")

    # -- sync primitive (add / edit / remove all go through here) -----------
    def _sync(self, list_id, *, created=None, changed=None, deleted=None) -> dict:
        ts = now_iso()
        body = {
            "changedShoppingListProperties": {
                "sortingStore": None, "title": None,
                "commentText": None, "latestChange": ts,
            },
            "createdRows": created or [],
            "changedRows": changed or [],
            "deletedRows": deleted or [],
        }
        # The gateway addresses lists by offlineId in the path (numeric ids 500).
        offline_id = self.resolve_list(list_id)["offlineId"]
        r = self._post(f"shoppinglistservice/v1/shoppinglists/{offline_id}/sync", body)
        try:
            return r.json()
        except ValueError:
            return {"status": r.status_code}

    def add_item(self, list_id, product_name: str, quantity: float | None = None,
                 unit: str | None = None) -> dict:
        """Add one item to an existing list via the sync endpoint (createdRows)."""
        row = {
            "productName": product_name,
            "isStrikedOver": False,
            "quantity": quantity,
            "unit": unit,
            "internalOrder": 0,
            "latestChange": now_iso(),       # required
            "offlineId": str(uuid.uuid4()),  # required
        }
        return self._sync(list_id, created=[row])

    def edit_item(self, list_selector, query: str, *, product_name: str | None = None,
                  quantity: float | None = None, unit: str | None = None,
                  checked: bool | None = None) -> dict:
        """Change an existing row (matched by name/offlineId) via changedRows.

        Only the fields you pass are overridden; the rest are preserved from the
        current row so the server keeps them. Returns {list, row, result}.
        """
        sl = self.resolve_list(list_selector)
        src = self.find_row(sl, query)
        row = {
            "offlineId": src["offlineId"],   # same id -> update, not insert
            "productName": product_name if product_name is not None else src.get("productName"),
            "quantity": quantity if quantity is not None else src.get("quantity"),
            "unit": unit if unit is not None else src.get("unit"),
            "isStrikedOver": checked if checked is not None else bool(src.get("isStrikedOver")),
            "internalOrder": src.get("internalOrder", 0),
            "latestChange": now_iso(),       # required, bump so the change wins
        }
        result = self._sync(sl.get("id"), changed=[row])
        return {"list": sl, "row": src, "result": result}

    def remove_item(self, list_selector, query: str) -> dict:
        """Delete a row (matched by name/offlineId) via deletedRows (by offlineId)."""
        sl = self.resolve_list(list_selector)
        src = self.find_row(sl, query)
        result = self._sync(sl.get("id"), deleted=[src["offlineId"]])
        return {"list": sl, "row": src, "result": result}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _creds(args) -> tuple[str, str]:
    user = args.user or os.environ.get("ICA_USER") or input("Personnummer: ").strip()
    pw = args.password or os.environ.get("ICA_PASS") or getpass.getpass("Password: ")
    return user, pw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Unofficial ICA Handla shopping-list client")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--access-token", help="use a captured access token (skip login)")
    ap.add_argument("--refresh-token", help="use a captured refresh token (skip login)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("register", help="dynamic client registration (DCR) only")

    p_login = sub.add_parser("login", help="register + log in with personnummer/password")
    p_login.add_argument("-u", "--user", help="personnummer (or env ICA_USER)")
    p_login.add_argument("-p", "--password", help="password (or env ICA_PASS); prompt if omitted")

    sub.add_parser("refresh", help="refresh the access token")
    sub.add_parser("lists", help="show shopping lists")

    p_add = sub.add_parser("add", help="add an item to a list")
    p_add.add_argument("item", help="product name, e.g. 'Mjölk'")
    p_add.add_argument("--list", dest="list_id", help="list id or name (default: first list)")
    p_add.add_argument("--qty", type=float, default=None)
    p_add.add_argument("--unit", default=None)

    p_edit = sub.add_parser("edit", help="change an item (match by name or offlineId)")
    p_edit.add_argument("item", help="current product name or offlineId")
    p_edit.add_argument("--list", dest="list_id", help="list id or name (default: first list)")
    p_edit.add_argument("--name", default=None, help="new product name")
    p_edit.add_argument("--qty", type=float, default=None, help="new quantity")
    p_edit.add_argument("--unit", default=None, help="new unit")
    g = p_edit.add_mutually_exclusive_group()
    g.add_argument("--check", dest="checked", action="store_true", default=None,
                   help="mark as struck over / done")
    g.add_argument("--uncheck", dest="checked", action="store_false", default=None,
                   help="un-strike")

    p_rm = sub.add_parser("remove", help="remove an item (match by name or offlineId)")
    p_rm.add_argument("item", help="product name or offlineId")
    p_rm.add_argument("--list", dest="list_id", help="list id or name (default: first list)")

    args = ap.parse_args(argv)
    c = IcaClient(verbose=args.verbose)

    if args.access_token:
        c.access_token = args.access_token
        c._save_state()
    if args.refresh_token:
        c.refresh_token = args.refresh_token
        c._save_state()

    if args.cmd == "register":
        c.register_client(force=True)
        print("client_id:", c.client_id)
        return 0

    if args.cmd == "login":
        user, pw = _creds(args)
        c.login(user, pw)
        print("Logged in. Access token stored in", STATE_FILE)
        return 0

    if args.cmd == "refresh":
        c.refresh()
        print("Refreshed. Stored in", STATE_FILE)
        return 0

    if args.cmd == "lists":
        for sl in c.shopping_lists():
            print(f"{sl.get('id')}\t{sl.get('title')}\t({len(sl.get('rows') or [])} rows)")
        return 0

    if args.cmd == "add":
        sl = c.resolve_list(args.list_id)
        c.add_item(sl.get("id"), args.item, quantity=args.qty, unit=args.unit)
        print(f"Added '{args.item}' to list {sl.get('id')} ({sl.get('title')}).")
        return 0

    if args.cmd == "edit":
        res = c.edit_item(args.list_id, args.item, product_name=args.name,
                          quantity=args.qty, unit=args.unit, checked=args.checked)
        label = args.name or res["row"].get("productName")
        print(f"Edited '{res['row'].get('productName')}' -> '{label}' "
              f"in list {res['list'].get('id')} ({res['list'].get('title')}).")
        return 0

    if args.cmd == "remove":
        res = c.remove_item(args.list_id, args.item)
        print(f"Removed '{res['row'].get('productName')}' "
              f"from list {res['list'].get('id')} ({res['list'].get('title')}).")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
