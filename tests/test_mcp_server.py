import json
import sys
from pathlib import Path

import pytest
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError

from fosset import mcp_server
from fosset.mcp_server import ChartPick, Label, visualize

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture
def renders(monkeypatch):
    """fake the window process: write a png per chart in the final picks and say it's done"""
    calls = []

    def fake_render(source, specs_file, work, title, show):
        answer = json.loads(specs_file.read_text())
        calls.append({"source": source, "answer": answer, "title": title, "show": show})
        (work / "png").mkdir()
        files = [f"{i:02d}-chart.png" for i in range(1, len(answer["charts"]) + 2)]  # plus the table
        for name in files:
            (work / "png" / name).write_bytes(b"\x89PNG fake")
        return files, "opened a window for the user"

    monkeypatch.setattr(mcp_server, "_render", fake_render)
    monkeypatch.setattr(mcp_server, "_has_display", lambda: True)
    return calls


def test_visualize_a_file(renders):
    result = visualize(path=str(EXAMPLES / "orders.csv"))
    report, images = result[0], result[1:]
    assert report.startswith("orders.csv: 400 rows, 5 columns")
    assert "  status: category, 3 distinct, e.g. paid" in report
    assert "1. Rows over time by status [line x=created_at color=status]" in report
    assert "opened a window for the user" in report
    assert len(images) == 4 and all(isinstance(i, Image) for i in images)  # capped, table never included
    assert renders[0]["show"] is True


def test_claudes_picks_go_first_and_bad_ones_get_reported(renders):
    result = visualize(
        path=str(EXAMPLES / "orders.csv"),
        charts=[
            ChartPick(kind="bar", x="country", y=["amount"], title="Revenue by country"),
            ChartPick(kind="bar", x="planet", y=["amount"], title="Revenue by planet"),
        ],
        labels=[Label(column="amount", label="Amount (€)")],
    )
    report = result[0]
    assert "1. Revenue by country [bar x=country y=amount]" in report
    assert 'dropped your pick "Revenue by planet"' in report
    assert '  amount ("Amount (€)"): number' in report
    answer = renders[0]["answer"]
    assert answer["charts"][0]["title"] == "Revenue by country"  # the window shows the same order
    assert answer["labels"] == [{"column": "amount", "label": "Amount (€)"}]


def test_inline_data(renders):
    result = visualize(data='[{"plan": "free", "users": 10}, {"plan": "pro", "users": 3}]', title="users by plan")
    assert result[0].startswith("users by plan: 2 rows, 2 columns")
    assert renders[0]["source"].name == "data.json"
    assert renders[0]["title"] == "users by plan"


def test_show_false_is_passed_through(renders):
    visualize(path=str(EXAMPLES / "usage.xml"), show=False)
    assert renders[0]["show"] is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "exactly one"),
        ({"path": "a.json", "data": "[]"}, "exactly one"),
        ({"data": "x" * 100_001}, "write it to a file"),
        ({"path": "/nope/missing.json"}, "couldn't read that"),
        ({"data": "[]"}, "any rows"),
    ],
)
def test_bad_input(renders, kwargs, message):
    with pytest.raises(ToolError, match=message):
        visualize(**kwargs)


def test_no_display_writes_html(monkeypatch):
    monkeypatch.setattr(mcp_server, "_has_display", lambda: False)
    result = visualize(path=str(EXAMPLES / "signups.json"))
    assert len(result) == 1
    page = result[0].split("the charts are in ")[1].split(" for any browser")[0]
    assert Path(page).read_text().startswith("<!doctype html>")


@pytest.mark.skipif(sys.platform != "darwin", reason="real rendering needs the macos webview")
def test_real_render_off_screen():
    result = visualize(path=str(EXAMPLES / "usage.xml"), show=False)
    images = result[1:]
    assert "rendered off screen" in result[0]
    assert len(images) == 3  # two bar charts and the scatter, not the table
    assert images[0].path.read_bytes().startswith(b"\x89PNG")
