import io
import sys
from pathlib import Path

import pytest

from fosset import cli, readers

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture
def shown(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "show", lambda figures, title, stem, started: calls.append((figures, title, stem)))
    return calls


@pytest.mark.parametrize("name", ["signups.json", "orders.csv", "usage.xml", "summary.json"])
def test_examples_open_with_charts(shown, name):
    cli.main([str(EXAMPLES / name)])
    figures, title, stem = shown[0]
    assert len(figures) >= 2  # at least one chart plus the table
    assert title.startswith(f"fosset · {name} · ")
    assert stem == Path(name).stem


def test_reads_stdin(shown, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'\xef\xbb\xbfplan,users\nfree,3\npro,1\n')))
    cli.main([])
    figures, title, _ = shown[0]
    assert title == "fosset · stdin · 2 rows"
    assert figures[0]["data"][0]["y"] == ["free", "pro"]  # BOM did not end up in the column name


def test_bad_input_exits_with_a_message(tmp_path, shown):
    bad = tmp_path / "bad.json"
    bad.write_text('[{"a": 1},')
    with pytest.raises(SystemExit) as exit_info:
        cli.main([str(bad)])
    assert str(exit_info.value).startswith("fosset: ")
    assert not shown


def test_oversized_input_is_refused(tmp_path, monkeypatch, shown):
    monkeypatch.setattr(cli, "MAX_BYTES", 10)
    big = tmp_path / "big.csv"
    big.write_text("a\n" + "1\n" * 20)
    with pytest.raises(SystemExit, match="keeps it small"):
        cli.main([str(big)])


def test_empty_input(tmp_path, shown):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(SystemExit, match="any rows"):
        cli.main([str(empty)])
