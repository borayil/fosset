import json

import pytest

from fosset import readers
from fosset.readers import detect_format, read


@pytest.mark.parametrize(
    ("text", "filename", "expected"),
    [
        ('[{"a": 1}]', "report.json", "json"),
        ("a,b\n1,2", "report.csv", "csv"),
        ("a\tb\n1\t2", "report.tsv", "csv"),
        ("<rows/>", "report.xml", "xml"),
        ('  {"a": 1}', None, "json"),
        ("[1, 2]", "stdin", "json"),
        ("<?xml version='1.0'?><rows/>", None, "xml"),
        ("a;b\n1;2", None, "csv"),
        ('{"a": 1}', "notes.txt", "json"),
    ],
)
def test_detect_format(text, filename, expected):
    assert detect_format(text, filename) == expected


# json


def test_json_array_of_objects_flattens_nested_keys():
    table = read(json.dumps([
        {"day": "2026-10-01", "stats": {"users": 5, "plan": {"name": "pro"}}, "tags": ["a"]},
        {"day": "2026-10-02", "extra": True},
    ]), "json")
    assert table.columns == ["day", "stats.users", "stats.plan.name", "tags", "extra"]
    assert table.rows[0]["stats.plan.name"] == "pro"
    assert table.rows[0]["tags"] == '["a"]'


def test_json_finds_rows_wrapped_in_an_envelope():
    text = json.dumps({"meta": {"count": 2}, "result": {"rows": [{"a": 1}, {"a": 2}]}})
    assert read(text, "json").rows == [{"a": 1}, {"a": 2}]


def test_json_picks_the_largest_record_list():
    text = json.dumps({"errors": [{"e": 1}], "data": [{"a": 1}, {"a": 2}, {"a": 3}]})
    assert len(read(text, "json").rows) == 3


def test_json_dict_of_dicts_becomes_keyed_rows():
    table = read(json.dumps({"free": {"users": 10}, "pro": {"users": 3}}), "json")
    assert table.rows == [{"key": "free", "users": 10}, {"key": "pro", "users": 3}]


def test_json_single_object_becomes_one_row():
    table = read(json.dumps({"total_users": 5, "active": 2}), "json")
    assert table.rows == [{"total_users": 5, "active": 2}]


def test_json_list_of_lists_uses_first_row_as_header():
    table = read(json.dumps([["plan", "users"], ["free", 10], ["pro", 3]]), "json")
    assert table.rows == [{"plan": "free", "users": 10}, {"plan": "pro", "users": 3}]


def test_json_list_of_lists_without_header():
    table = read(json.dumps([[1, 2], [3, 4]]), "json")
    assert table.columns == ["col1", "col2"]


def test_json_list_of_scalars():
    assert read("[3, 1, 2]", "json").rows == [{"value": 3}, {"value": 1}, {"value": 2}]


def test_json_lines():
    table = read('{"a": 1}\n{"a": 2}\n\n{"a": 3}\n', "json")
    assert [r["a"] for r in table.rows] == [1, 2, 3]


def test_broken_json_raises():
    with pytest.raises(json.JSONDecodeError):
        read('[{"a": 1},', "json")


def test_rows_are_capped(monkeypatch):
    monkeypatch.setattr(readers, "MAX_ROWS", 2)
    table = read("[1, 2, 3]", "json")
    assert len(table.rows) == 2
    assert table.truncated


# csv


def test_csv_comma():
    table = read("plan,users\nfree,10\npro,\n", "csv")
    assert table.rows == [{"plan": "free", "users": "10"}, {"plan": "pro", "users": None}]


def test_csv_semicolon_and_tab():
    assert read("a;b\n1;2\n3;4\n", "csv").rows[1] == {"a": "3", "b": "4"}
    assert read("a\tb\n1\t2\n3\t4\n", "csv").rows[1] == {"a": "3", "b": "4"}


def test_csv_quoted_values_and_blank_lines():
    table = read('name,note\n"Smith, J","said ""hi"""\n\n"Doe",x\n', "csv")
    assert table.rows == [{"name": "Smith, J", "note": 'said "hi"'}, {"name": "Doe", "note": "x"}]


def test_csv_single_column():
    assert read("users\n1\n2\n", "csv").rows == [{"users": "1"}, {"users": "2"}]


def test_csv_blank_header_gets_a_name():
    assert read(",b\n1,2\n", "csv").columns == ["col1", "b"]


def test_empty_csv():
    assert read("", "csv").rows == []


# xml


def test_xml_attribute_rows():
    table = read('<report><row feature="search" calls="10"/><row feature="login" calls="4"/></report>', "xml")
    assert table.rows == [{"feature": "search", "calls": "10"}, {"feature": "login", "calls": "4"}]


def test_xml_child_element_rows_with_nesting():
    text = """<?xml version="1.0" encoding="UTF-8"?>
    <response>
      <meta><count>2</count></meta>
      <orders>
        <order id="1"><amount currency="EUR">10.5</amount><customer><country>DE</country></customer></order>
        <order id="2"><amount currency="EUR">3</amount><customer><country>TR</country></customer></order>
      </orders>
    </response>"""
    table = read(text, "xml")
    assert table.rows[0] == {"id": "1", "amount.currency": "EUR", "amount": "10.5", "customer.country": "DE"}
    assert len(table.rows) == 2


def test_xml_prefers_records_nearest_the_root():
    # each order repeats <item> but the orders are the actual rows
    text = "<orders>" + "<order><item>a</item><item>b</item><item>c</item></order>" * 2 + "</orders>"
    assert len(read(text, "xml").rows) == 2


def test_xml_strips_namespaces():
    text = '<r xmlns="urn:x"><row><v>1</v></row><row><v>2</v></row></r>'
    assert read(text, "xml").rows == [{"v": "1"}, {"v": "2"}]


def test_xml_single_record():
    assert read("<user><name>Ada</name><age>36</age></user>", "xml").rows == [{"name": "Ada", "age": "36"}]


def test_xml_text_only_records():
    assert read("<values><v>1</v><v>2</v></values>", "xml").rows == [{"value": "1"}, {"value": "2"}]


def test_load_reads_files_and_drops_the_bom(tmp_path):
    f = tmp_path / "r.csv"
    f.write_bytes(b"\xef\xbb\xbfa,b\n1,2\n")
    assert readers.load(str(f)) == ("a,b\n1,2\n", "r.csv")


def test_decode_refuses_big_input(monkeypatch):
    monkeypatch.setattr(readers, "MAX_BYTES", 3)
    with pytest.raises(ValueError, match="keeps it small"):
        readers.decode(b"abcd")
