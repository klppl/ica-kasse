"""Curity authentication: dynamic client registration, PKCE login, refresh.

Flow (reverse-engineered from the app):
  1. bootstrap  -> registration token   (client_credentials, scope=dcr)
  2. register   -> ephemeral client      (POST /register, software_id)
  3. authorize  -> HTML login form       (PKCE S256, acr=html-form password)
  4. token      -> access + refresh      (authorization_code + code_verifier)
"""
from __future__ import annotations

import logging
import secrets
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import requests

from . import const, http, pkce
from .config import State
from .errors import AuthError

_LOG = logging.getLogger("ica_handla.auth")

# The authorize/login pages return an empty ``{}`` for ``Accept: application/json``
# (the session default), so the browser-style flow must ask for HTML.
_HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


# --- minimal HTML form parser (no BeautifulSoup dependency) ----------------
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
                         "fields": {}, "types": {}}
            self.forms.append(self._cur)
        elif tag in ("input", "button") and self._cur is not None and a.get("name"):
            self._cur["fields"][a["name"]] = a.get("value", "")
            self._cur["types"][a["name"]] = a.get("type", "text").lower()

    def handle_endtag(self, tag):
        if tag == "form":
            self._cur = None


def _parse_forms(html: str) -> list[dict]:
    p = _FormParser()
    p.feed(html)
    return p.forms


class Authenticator:
    def __init__(self, state: State, session: requests.Session | None = None):
        self.state = state
        self.session = session or http.make_session()

    # -- DCR ---------------------------------------------------------------
    def register_client(self, force: bool = False) -> None:
        if self.state.client_id and not force:
            return
        r = http.request(
            self.session, "POST", const.IMS_BASE + const.TOKEN_ENDPOINT,
            data={
                "client_id": const.DCR_CLIENT_ID,
                "client_secret": const.DCR_CLIENT_SECRET,
                "grant_type": const.DCR_GRANT_TYPE,
                "scope": const.DCR_SCOPE,
                "response_type": const.TOKEN_RESPONSE_TYPE,
            },
        )
        reg = http.json_or_raise(r, context="DCR bootstrap")
        reg_token = reg.get("access_token")
        if not reg_token:
            raise AuthError("DCR bootstrap returned no token", code="auth_failed")

        r = http.request(
            self.session, "POST", const.IMS_BASE + const.REGISTER_ENDPOINT,
            headers={"Authorization": f"Bearer {reg_token}"},
            json={"software_id": const.DCR_SOFTWARE_ID},
        )
        d = http.json_or_raise(r, context="client registration")
        self.state.client_id = d["client_id"]
        self.state.client_secret = d["client_secret"]
        self.state.client_scope = d.get("scope", const.AUTH_SCOPE)
        self.state.save()
        _LOG.info("registered client %s", self.state.client_id)

    # -- interactive login -------------------------------------------------
    def login(self, username: str, password: str) -> None:
        self.register_client()
        verifier = pkce.new_verifier()
        st = secrets.token_urlsafe(16)
        params = {
            "client_id": self.state.client_id,
            "scope": const.AUTH_SCOPE,
            "response_type": "code",
            "prompt": "login",
            "redirect_uri": const.REDIRECT_URI,
            "max_age": "0",
            "state": st,
            "nonce": secrets.token_urlsafe(16),
            "_cb": str(int(time.time() * 1000)),
            "code_challenge": pkce.challenge(verifier),
            "code_challenge_method": pkce.challenge_method(),
            "acr": const.ACR_PASSWORD,
        }
        r = self._request("GET", const.IMS_BASE + const.AUTHORIZE_ENDPOINT,
                          params=params, headers=_HTML_HEADERS)
        code = self._walk_login_forms(r, username, password)
        if not code:
            raise AuthError(
                "login did not yield an authorization code; the password may be "
                "wrong or Curity added a step (consent/OTP/BankID). Re-run with -v, "
                "or import a captured refresh token with `ica token`.",
                code="auth_failed",
            )
        self._exchange_code(code, verifier)
        self.state.username = username
        self.state.save()

    def _request(self, method: str, url: str, *, max_redirects: int = 10,
                 **kw) -> requests.Response:
        """Like ``http.request`` but follows redirects by hand.

        The final hop is a 302 to the app's custom scheme (``icacurity://``),
        which ``requests`` cannot follow; we stop there and read the code from
        its ``Location`` header (see ``_code_from``).
        """
        resp = http.request(self.session, method, url, allow_redirects=False, **kw)
        for _ in range(max_redirects):
            loc = resp.headers.get("location")
            if resp.status_code not in (301, 302, 303, 307, 308) or not loc:
                break
            nxt = requests.compat.urljoin(resp.url, loc)
            if urlparse(nxt).scheme not in ("http", "https"):
                break
            if resp.status_code in (301, 302, 303):
                method, kw = "GET", {k: v for k, v in kw.items() if k not in ("data", "json", "params")}
            resp = http.request(self.session, method, nxt, allow_redirects=False, **kw)
        return resp

    def _walk_login_forms(self, resp: requests.Response, username: str,
                          password: str, max_steps: int = 6) -> str | None:
        sent_password = False
        for step in range(max_steps):
            code = self._code_from(resp)
            if code:
                return code
            if sent_password and resp.status_code >= 400:
                # Curity re-renders the form (HTTP 400) on bad credentials; never
                # resubmit, repeated attempts can lock the account.
                raise AuthError("wrong personnummer and/or password",
                                code="auth_failed", http_status=resp.status_code)
            forms = _parse_forms(resp.text)
            if not forms:
                _LOG.info("no form at step %d (url=%s)", step, resp.url)
                return None
            form = self._pick_form(forms)
            data = dict(form["fields"])
            for name, ftype in form["types"].items():
                low = name.lower()
                if ftype == "password" or "password" in low:
                    data[name] = password
                elif "user" in low or low in ("username", "personalnumber", "ssn"):
                    data[name] = username
            data.setdefault("userName", username)
            data.setdefault("password", password)
            sent_password = sent_password or any(
                t == "password" or "password" in n.lower() for n, t in form["types"].items())
            action = requests.compat.urljoin(resp.url, form["action"] or resp.url)
            _LOG.info("submitting form step %d -> %s", step, action)
            method = "GET" if form["method"] == "get" else "POST"
            kw = {"params": data} if method == "GET" else {"data": data}
            resp = self._request(method, action, headers=_HTML_HEADERS, **kw)
        return self._code_from(resp)

    @staticmethod
    def _pick_form(forms: list[dict]) -> dict:
        for f in forms:
            if any(t == "password" or "password" in n.lower()
                   for n, t in f["types"].items()):
                return f
        return forms[0]

    @staticmethod
    def _code_from(resp: requests.Response) -> str | None:
        urls = [resp.url, resp.headers.get("location", "")] + [
            h.headers.get("location", "") for h in resp.history]
        for u in urls:
            if not u:
                continue
            pu = urlparse(u)
            if pu.scheme == const.REDIRECT_SCHEME or "code=" in u:
                qs = parse_qs(pu.query)
                if "code" in qs:
                    return qs["code"][0]
        return None

    # -- token exchange / refresh ------------------------------------------
    def _store_token(self, d: dict) -> None:
        self.state.access_token = d.get("access_token")
        self.state.refresh_token = d.get("refresh_token", self.state.refresh_token)
        self.state.token_scope = d.get("scope", self.state.token_scope)
        exp = d.get("expires_in")
        self.state.expires_at = (time.time() + float(exp)) if exp else None
        self.state.save()

    def _exchange_code(self, code: str, verifier: str) -> None:
        r = http.request(
            self.session, "POST", const.IMS_BASE + const.TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": self.state.client_id,
                "client_secret": self.state.client_secret,
                "grant_type": const.TOKEN_GRANT_TYPE,
                "scope": self.state.client_scope or const.AUTH_SCOPE,
                "response_type": const.TOKEN_RESPONSE_TYPE,
                "code_verifier": verifier,
                "redirect_uri": const.REDIRECT_URI,
            },
        )
        self._store_token(http.json_or_raise(r, context="token exchange"))

    def refresh(self) -> None:
        if not self.state.refresh_token:
            raise AuthError("no refresh token; run `ica login` first", code="missing_credentials")
        if not self.state.client_id:
            raise AuthError("no registered client; run `ica login` first", code="missing_credentials")
        r = http.request(
            self.session, "POST", const.IMS_BASE + const.TOKEN_ENDPOINT,
            data={
                "refresh_token": self.state.refresh_token,
                "client_id": self.state.client_id,
                "client_secret": self.state.client_secret,
                "grant_type": const.REFRESH_GRANT_TYPE,
                "scope": self.state.token_scope or self.state.client_scope or const.AUTH_SCOPE,
                "response_type": const.TOKEN_RESPONSE_TYPE,
                "redirect_uri": const.REDIRECT_URI,
            },
        )
        if r.status_code >= 400:
            raise AuthError("token refresh failed; run `ica login` again",
                            code="auth_failed", http_status=r.status_code)
        self._store_token(http.json_or_raise(r, context="token refresh"))

    def bearer(self, refresh_margin: float = 60.0) -> str:
        """Return a usable access token, refreshing proactively if near expiry."""
        if not self.state.access_token:
            raise AuthError("not logged in; run `ica login` first", code="missing_credentials")
        if self.state.expires_at and self.state.refresh_token:
            if time.time() >= self.state.expires_at - refresh_margin:
                _LOG.info("access token near/at expiry, refreshing")
                self.refresh()
        return self.state.access_token

    def revoke(self) -> None:
        if not (self.state.client_id and self.state.access_token):
            return
        try:
            http.request(
                self.session, "POST", const.IMS_BASE + const.REVOKE_ENDPOINT,
                data={
                    "client_id": self.state.client_id,
                    "client_secret": self.state.client_secret,
                    "token": self.state.access_token,
                },
            )
        except Exception as e:  # noqa: BLE001
            _LOG.info("revoke failed (ignored): %s", e)
