"""IcaApi request shapes against the apimgw-pub gateway (mocked HTTP)."""
import json

import pytest
import responses

from ica_handla import const
from ica_handla.api import IcaApi
from ica_handla.auth import Authenticator
from ica_handla.config import State

LIST = {"id": 1, "offlineId": "AAAA-BBBB", "title": "Handla", "rows": []}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("ICA_HANDLA_STATE_PATH", str(tmp_path / "state.json"))
    st = State(access_token="tok")
    return IcaApi(Authenticator(st))


def _lists(rsps):
    rsps.add(responses.GET, const.API_BASE + const.EP_LISTS,
             json={"shoppingLists": [LIST]})


def test_api_base_is_gateway():
    assert const.API_BASE == "https://apimgw-pub.ica.se/sverige/digx/mobile/"


@responses.activate
def test_recipe_search_uses_get_with_params(api):
    responses.add(responses.GET, const.API_BASE + const.EP_RECIPE_SEARCH, json={"recipes": []})
    api.recipe_search("köttbullar")
    assert responses.calls[0].request.method == "GET"
    url = responses.calls[0].request.url
    assert "phrase=" in url and "freeText" not in url and "api-version=2" in url


@responses.activate
def test_sync_addresses_list_by_offline_id(api):
    _lists(responses)
    url = const.API_BASE + const.EP_LIST_SYNC.format(id="AAAA-BBBB")
    responses.add(responses.POST, url, json={})
    api.add_item("Handla", "2 st mjölk")
    sent = json.loads(responses.calls[-1].request.body)
    assert responses.calls[-1].request.url == url
    assert sent["createdRows"][0]["productName"] == "mjölk"


@responses.activate
def test_delete_list_sends_offline_id(api):
    _lists(responses)
    responses.add(responses.POST, const.API_BASE + const.EP_LISTS_DELETE, json={})
    api.delete_list(1)
    assert json.loads(responses.calls[-1].request.body) == ["AAAA-BBBB"]


@responses.activate
def test_offers_search_body_and_api_version(api):
    responses.add(responses.POST, const.API_BASE + const.EP_OFFERS_SEARCH, json={"storeOffers": []})
    api.offers_search([2006022026], ["1066"])
    req = responses.calls[0].request
    assert "api-version=2" in req.url
    assert json.loads(req.body) == {"offerIds": ["2006022026"], "storeIds": [1066]}


@responses.activate
def test_user_discounts_body(api):
    responses.add(responses.POST, const.API_BASE + const.EP_USER_DISCOUNTS, json={"stores": []})
    api.user_discounts([1066])
    assert json.loads(responses.calls[0].request.body) == {"storeIds": [1066]}
