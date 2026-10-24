"""Offline tests for the MCP wrapper (the `mcp` SDK is not required to run these)."""
import pytest

from ica_handla import mcp_server as m
from ica_handla.config import State


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ICA_HANDLA_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.delenv("ICA_HANDLA_STORE_ID", raising=False)
    monkeypatch.delenv("ICA_HANDLA_COOKIE", raising=False)


def test_tool_names_unique_and_expected():
    names = [t.__name__ for t in m.TOOLS]
    assert len(names) == len(set(names))
    for required in ("add_item", "show_list", "handla_cart_add", "auth_status"):
        assert required in names


def test_auth_status_empty():
    r = m.auth_status()
    assert r["ok"] and r["data"]["logged_in"] is False


def test_list_tool_wraps_data(monkeypatch):
    monkeypatch.setattr("ica_handla.api.IcaApi.lists",
                        lambda self: [{"id": 1, "title": "Hemma", "rows": [{}, {}]}])
    assert m.list_shopping_lists() == {"ok": True, "data": [{"id": 1, "title": "Hemma", "rows": 2}]}


def test_error_is_structured_not_raised():
    r = m.handla_cart_show(store_id="1004261")  # no cookie saved
    assert r["ok"] is False and r["code"] == "missing_handla_web_session"


def test_build_server_without_sdk_exits():
    # mcp isn't installed in CI for this package's base deps.
    pytest.importorskip  # noqa: B018
    try:
        import mcp  # noqa: F401
    except ImportError:
        with pytest.raises(SystemExit):
            m.build_server()
