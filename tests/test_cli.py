import io
import sys
from pathlib import Path

import pytest

from fosset import cli, llm

EXAMPLES = Path(__file__).parent.parent / "examples"

ANSWER = {
    "charts": [{"kind": "bar", "x": "plan", "y": ["signups"], "color": "", "title": "Signups by plan, from the llm"}],
    "labels": [{"column": "signups", "label": "New signups"}],
}


class Shown(list):
    """every window that would have opened, plus the status and background job of the last one"""

    status = ""
    later = None


@pytest.fixture
def shown(monkeypatch):
    calls = Shown()

    def fake_show(figures, title, stem, started, status="", later=None):
        calls.append((figures, title, stem))
        calls.status, calls.later = status, later

    monkeypatch.setattr(cli, "show", fake_show)
    return calls


@pytest.fixture
def llm_on(monkeypatch):
    llm.CONFIG_PATH.write_text('[llm]\nprovider = "anthropic"\n')
    asked = []

    def fake_ask(config, summary):
        asked.append(summary)
        return ANSWER

    monkeypatch.setattr(llm, "ask", fake_ask)
    return asked


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


def test_llm_picks_come_in_later_and_get_cached(shown, llm_on):
    cli.main([str(EXAMPLES / "signups.json")])
    assert shown.status == "asking claude-opus-5-5…"
    figures, status = shown.later()
    assert status == "picked by claude-opus-5-5"
    assert figures[0]["layout"]["title"]["text"] == "Signups by plan, from the llm"
    assert figures[0]["layout"]["xaxis"]["title"]["text"] == "New signups"
    assert figures[-1]["layout"]["title"]["text"] == "Data"  # rule picks and the table still follow
    assert len(llm_on) == 1

    # same column layout again: straight from the cache, no second call
    cli.main([str(EXAMPLES / "signups.json")])
    figures, _, _ = shown[1]
    assert shown.later is None
    assert shown.status == "picked by claude-opus-5-5 (cached)"
    assert figures[0]["layout"]["title"]["text"] == "Signups by plan, from the llm"
    assert len(llm_on) == 1


def test_llm_failure_keeps_the_rule_picks(shown, llm_on, monkeypatch):
    def broken(config, summary):
        raise llm.LLMError("nope")

    monkeypatch.setattr(llm, "ask", broken)
    cli.main([str(EXAMPLES / "signups.json")])
    assert shown.later() == (None, "llm didn't work out, these are the rule picks")


def test_no_llm_flag(shown, llm_on):
    cli.main([str(EXAMPLES / "signups.json"), "--no-llm"])
    assert shown.later is None
    assert shown.status == ""


def test_broken_config_falls_back_to_rules(shown, capsys):
    llm.CONFIG_PATH.write_text('[llm]\nprovider = "openai"\n')
    cli.main([str(EXAMPLES / "signups.json")])
    assert shown.later is None
    assert "ignoring the llm config" in capsys.readouterr().err
