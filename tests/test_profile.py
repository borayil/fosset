from datetime import datetime

import pytest

from fosset.profile import profile, to_datetime, to_number
from fosset.readers import Table


def kinds(rows):
    columns = list(dict.fromkeys(k for r in rows for k in r))
    return {name: col.kind for name, col in profile(Table(columns, rows)).items()}


def test_column_kinds():
    rows = [
        {
            "id": i,
            "user_uuid": "0b8e4a3e-7f1c-4c55-9d2e-1a2b3c4d5e6f",
            "day": f"2026-10-{i + 1:02d}",
            "plan": ["free", "pro"][i % 2],
            "revenue": str(i * 1.5),
            "active": i % 2 == 0,
            "note": "a long free text comment that nobody wants on a chart axis",
            "missing": None,
        }
        for i in range(10)
    ]
    assert kinds(rows) == {
        "id": "id",
        "user_uuid": "id",
        "day": "datetime",
        "plan": "category",
        "revenue": "number",
        "active": "category",
        "note": "text",
        "missing": "empty",
    }


def test_uuid_values_are_ids_whatever_the_name():
    rows = [{"ref": f"0b8e4a3e-7f1c-4c55-9d2e-1a2b3c4d5e{i:02d}"} for i in range(5)]
    assert kinds(rows) == {"ref": "id"}


def test_a_few_bad_values_do_not_change_the_kind():
    rows = [{"n": str(i)} for i in range(19)] + [{"n": "N/A"}]
    assert kinds(rows) == {"n": "number"}


def test_counts_and_uniqueness():
    col = profile(Table(["plan"], [{"plan": "a"}, {"plan": "b"}, {"plan": "a"}, {"plan": None}]))["plan"]
    assert (col.count, col.distinct, col.unique) == (3, 2, False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3, 3.0),
        ("1.5", 1.5),
        (" 42 ", 42.0),
        ("1e3", 1000.0),
        ("nan", None),
        (float("inf"), None),
        (True, None),
        ("12 apples", None),
        (None, None),
    ],
)
def test_to_number(value, expected):
    assert to_number(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-05", datetime(2026, 10, 5)),
        ("2026-10", datetime(2026, 10, 1)),
        ("2026-10-05T10:00:00Z", datetime(2026, 10, 5, 10)),
        ("2026-10-05T12:00:00+02:00", datetime(2026, 10, 5, 10)),  # converted to UTC
        ("2026-10-05 10:00:00.5+00", datetime(2026, 10, 5, 10, 0, 0, 500000)),  # postgres text format
        ("10/31/2026", datetime(2026, 10, 31)),
        ("31.10.2026", datetime(2026, 10, 31)),
        ("free", None),
        ("2026", None),
        (20261005, None),
    ],
)
def test_to_datetime(value, expected):
    assert to_datetime(value) == expected


def kinds_with(rows, separators):
    columns = list(dict.fromkeys(k for r in rows for k in r))
    return profile(Table(columns, rows, separators=separators))


def test_numbers_written_out_for_people_with_a_turkish_hint():
    rows = [
        {"kisi": "1.464", "ciro": "21.985.979 ₺", "oran": "%44", "puan": "12.5", "kesir": "0.875"},
        {"kisi": "820", "ciro": "4.120 ₺", "oran": "%7", "puan": "3.25", "kesir": "1.500"},
    ]
    columns = kinds_with(rows, (",", "."))
    assert {c.name: c.kind for c in columns.values()} == dict.fromkeys(rows[0], "number")
    assert [columns["kisi"].parse(r["kisi"]) for r in rows] == [1464.0, 820.0]
    assert columns["ciro"].parse("21.985.979 ₺") == 21985979.0
    # columns that can't be the turkish way keep the plain dot decimal
    assert [columns["puan"].parse(r["puan"]) for r in rows] == [12.5, 3.25]
    assert [columns["kesir"].parse(r["kesir"]) for r in rows] == [0.875, 1.5]


def test_without_the_hint_dots_stay_decimals():
    rows = [{"kisi": "1.464", "ciro": "21.985.979 ₺"}, {"kisi": "820", "ciro": "4.120 ₺"}]
    columns = kinds_with(rows, (".", ","))
    assert columns["kisi"].kind == "number" and columns["kisi"].parse("1.464") == 1.464
    assert columns["ciro"].kind == "category"  # can't be read as one english number


def test_english_formatted_strings():
    rows = [{"revenue": "$1,234.50"}, {"revenue": "$980.00"}, {"revenue": "$12,000"}]
    column = kinds_with(rows, (".", ","))["revenue"]
    assert column.kind == "number" and column.parse("$12,000") == 12000.0
