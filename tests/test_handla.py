import json

import pytest

from ica_handla import handla
from ica_handla.cli import main
from ica_handla.config import State
from ica_handla.errors import AuthError, UsageError


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ICA_HANDLA_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.delenv("ICA_HANDLA_STORE_ID", raising=False)
    monkeypatch.delenv("ICA_HANDLA_COOKIE", raising=False)


def test_csrf_regex():
    html = '{"csrf":{"token":"0123abcd-1234-5678-9abc-def012345678"}}'
    assert handla._CSRF_RE.search(html).group(1) == "0123abcd-1234-5678-9abc-def012345678"


def test_compact_search_variants():
    client = handla.HandlaClient("1")
    out = client.compact_search({"products": [
        {"name": "Mjölk", "productId": "p1", "unitOfMeasure": "l"},
        {"title": "X", "id": "p2"},
        {"name": "NoId"},
    ]})
    assert out == [
        {"name": "Mjölk", "productId": "p1", "unitOfMeasure": "l"},
        {"name": "X", "productId": "p2"},
    ]


def test_apply_quantity_payload(monkeypatch):
    seen = {}
    client = handla.HandlaClient("1", cookie_header="a=b")
    monkeypatch.setattr(client, "apply_quantity", lambda u: seen.update(u=u))
    client.cart_add("pid", 2)
    assert seen["u"] == [{"productId": "pid", "quantity": 2}]
    client.cart_remove("pid", 3)
    assert seen["u"] == [{"productId": "pid", "quantity": -3}]


def test_resolve_store_id_precedence(monkeypatch):
    st = State()
    with pytest.raises(UsageError):
        handla.resolve_store_id(st, None)
    st.handla_store_id = "999"
    assert handla.resolve_store_id(st, None) == "999"
    assert handla.resolve_store_id(st, "111") == "111"  # explicit wins
    monkeypatch.setenv("ICA_HANDLA_STORE_ID", "222")
    assert handla.resolve_store_id(State(), None) == "222"


def test_resolve_cookie_missing():
    with pytest.raises(AuthError):
        handla.resolve_cookie(State())


def test_cli_login_status_logout(capsys):
    assert main(["handla", "login", "--cookie", "sess=abc", "--store-id", "1004261"]) == 0
    capsys.readouterr()
    assert State.load().handla_cookie == "sess=abc"
    main(["handla", "status"])
    status = json.loads(capsys.readouterr().out)["data"]
    assert status["has_cookie"] and status["store_id"] == "1004261"
    main(["handla", "logout"])
    capsys.readouterr()
    assert State.load().handla_cookie is None


def test_cart_without_cookie_errors(capsys):
    rc = main(["cart", "show", "--store-id", "1004261"])
    assert rc == 2
    assert json.loads(capsys.readouterr().err)["code"] == "missing_handla_web_session"


def test_browser_cookies_to_header_filters_host():
    from ica_handla import browser_login
    hdr = browser_login.cookies_to_header([
        {"domain": ".handlaprivatkund.ica.se", "name": "sess", "value": "x"},
        {"domain": "other.com", "name": "nope", "value": "y"},
        {"domain": "www.handlaprivatkund.ica.se", "name": "alb", "value": "z"},
    ])
    assert hdr == "sess=x; alb=z"


def test_browser_login_without_playwright_errors(capsys, monkeypatch):
    # Simulate playwright being unavailable regardless of environment.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    rc = main(["handla", "login", "--browser", "--store-id", "1004261"])
    assert rc == 1
    assert json.loads(capsys.readouterr().err)["code"] == "handla_browser_login_failed"
