import pytest

from ica_handla import models
from ica_handla.errors import NotFoundError, UsageError


# -- parse_line -------------------------------------------------------------
@pytest.mark.parametrize("line,expected", [
    ("mjölk", {"productName": "mjölk"}),
    ("2 st mjölk", {"productName": "mjölk", "quantity": 2.0, "unit": "st"}),
    ("1,5 l mellanmjölk", {"productName": "mellanmjölk", "quantity": 1.5, "unit": "l"}),
    ("3 äpplen", {"productName": "äpplen", "quantity": 3.0}),
    ("kg potatis", {"productName": "potatis", "unit": "kg"}),
])
def test_parse_line(line, expected):
    assert models.parse_line(line) == expected


def test_new_row_has_required_fields():
    row = models.new_row("Bröd", quantity=1.0, unit="st")
    assert row["productName"] == "Bröd"
    assert row["latestChange"] and row["offlineId"]
    assert row["isStrikedOver"] is False


def test_sync_body_shape():
    b = models.sync_body(created=[{"x": 1}])
    assert set(b) == {"changedShoppingListProperties", "createdRows", "changedRows", "deletedRows"}
    assert b["createdRows"] == [{"x": 1}]


# -- resolution -------------------------------------------------------------
LISTS = [
    {"id": 111, "offlineId": "o1", "title": "Hemma",
     "rows": [{"offlineId": "a1", "productName": "Mjölk"},
              {"offlineId": "a2", "productName": "Bröd"}]},
    {"id": 222, "offlineId": "o2", "title": "Lantgården", "rows": []},
]


def test_resolve_by_id_title_default():
    assert models.resolve_list(LISTS, "222")["title"] == "Lantgården"
    assert models.resolve_list(LISTS, "lant")["id"] == 222
    assert models.resolve_list(LISTS, None)["id"] == 111
    assert models.resolve_list(LISTS, "o1")["id"] == 111


def test_resolve_no_match_raises():
    with pytest.raises(NotFoundError):
        models.resolve_list(LISTS, "nope")


def test_find_row_by_name_and_offline_id():
    assert models.find_row(LISTS[0], "Bröd")["offlineId"] == "a2"
    assert models.find_row(LISTS[0], "a1")["productName"] == "Mjölk"


def test_find_row_ambiguous():
    lst = {"rows": [{"offlineId": "x", "productName": "Mjölk 3%"},
                    {"offlineId": "y", "productName": "Mjölk 1.5%"}]}
    with pytest.raises(UsageError):
        models.find_row(lst, "mjölk")
