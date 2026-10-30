"""the mcp server behind the claude code plugin. claude hands it data, plus its own chart
picks if it has opinions. you get a window, claude gets a digest of every chart and pngs
of the first few, so you're both looking at the same thing"""

import csv
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from fosset import llm
from fosset.charts import build, plural
from fosset.digest import describe
from fosset.profile import Column
from fosset.profile import profile as profile_columns
from fosset.readers import Table, detect_format, load, read
from fosset.recommend import Spec, recommend
from fosset.viewer import write_html

MAX_INLINE = 100_000
MAX_IMAGES = 4
# the very first window after a reboot takes a few seconds while macos loads webkit
RENDER_TIMEOUT = 15

DESCRIPTION = """Chart JSON, CSV or XML data. Opens a native window with the charts for the user, and \
returns a short numeric digest of every chart plus PNGs of the first few, so you see what they see.

Pass `path` (an absolute path to a file) or `data` (the raw text, for small results under 100k \
characters), not both. Leave `charts` empty to let fosset pick, or pass your own picks when the user \
cares about something specific; yours go first and fosset's fill in after. Chart kinds and the columns \
they take:
line: x is a datetime or number column, y is one number column (or empty to count rows), color is an \
optional category column that splits it into series.
bar: x is a category column, y is one number column (or empty to count rows).
scatter: x and y are number columns.
hist: x is a number column.
kpi: y is 1 to 12 number columns, only for data with exactly one row.
Picks that don't fit the columns get dropped, and the result says which."""

server = MCPServer("fosset")


class ChartPick(BaseModel):
    kind: Literal["line", "bar", "scatter", "hist", "kpi"]
    x: str = Field("", description="column for the x axis, empty for kpi")
    y: list[str] = Field(default_factory=list, description="number columns, empty on line or bar to count rows")
    color: str = Field("", description="category column that splits a line into series, or empty")
    title: str = Field("", description='short plain title in sentence case, like "Orders over time by status"')


class Label(BaseModel):
    column: str
    label: str = Field(description='a human name for the column, like "MRR (€)" for mrr_eur')


@server.tool(description=DESCRIPTION)
def visualize(
    path: str = "",
    data: str = "",
    charts: list[ChartPick] | None = None,
    labels: list[Label] | None = None,
    title: str = "",
    show: bool = True,
) -> list[str | Image]:
    if bool(path) == bool(data):
        raise ToolError("pass either path or data, exactly one of them")
    if len(data) > MAX_INLINE:
        raise ToolError(f"data is over {MAX_INLINE:,} characters, write it to a file and pass path instead")

    work = Path(tempfile.mkdtemp(prefix="fosset-"))
    try:
        if data:
            source = work / f"data.{detect_format(data)}"
            source.write_text(data)
            text, name = data, title or "data"
        else:
            source = Path(path).expanduser().resolve()
            text, name = load(str(source))
        table = read(text, detect_format(text, source.name))
    except (ValueError, OSError, ET.ParseError, csv.Error) as e:
        raise ToolError(f"couldn't read that: {e}") from e
    if not table.rows:
        raise ToolError("couldn't find any rows in there")

    # claude's picks are handled exactly like an llm answer: checked, then put in front of the rule picks
    columns = profile_columns(table)
    n_rows = len(table.rows)
    picks = [pick.model_dump() for pick in charts or []]
    answer = {"charts": picks, "labels": [label.model_dump() for label in labels or []]}
    dropped = [pick for pick in picks if not llm.to_specs({"charts": [pick]}, columns, n_rows)[0]]
    specs = llm.apply_answer(answer, columns, n_rows, recommend(columns, n_rows))
    figures = [build(spec, table, columns) for spec in specs]

    notes = [f'dropped your pick "{p["title"] or p["kind"]}", it doesn\'t fit the columns above' for p in dropped]
    if table.truncated:
        notes.append(f"only the first {n_rows:,} rows were used")
    images = []
    if _has_display():
        specs_file = work / "specs.json"
        specs_file.write_text(json.dumps(_as_answer(specs, columns)))
        files, note = _render(source, specs_file, work, title or name, show)
        notes.append(note)
        charts_only = [f for f, figure in zip(files, figures) if figure["data"][0]["type"] != "table"]
        images = [Image(path=work / "png" / f) for f in charts_only[:MAX_IMAGES]]
    else:
        page = work / "charts.html"
        write_html(figures, page)
        notes.append(f"there's no display here so no window, the charts are in {page} for any browser")
    if images:
        notes.append(f"pngs of the first {len(images)} charts follow")
    return [_report(name, table, columns, figures, notes), *images]


def _render(source: Path, specs_file: Path, work: Path, title: str, show: bool) -> tuple[list[str], str]:
    """the window runs in its own process, gui stuff can't live inside the mcp server. it
    saves every chart as a png first, and stays open for the user unless `show` is off"""
    png_dir = work / "png"
    log_path = work / "log.txt"
    command = [
        sys.executable, "-m", "fosset", str(source),
        "--specs", str(specs_file), "--png", str(png_dir), "--no-llm", "--title", title,
    ]
    if not show:
        command.append("--headless")
    with open(log_path, "w") as log:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, cwd=os.getcwd()
        )
    done = png_dir / "done.json"
    deadline = time.monotonic() + RENDER_TIMEOUT
    while not done.exists():
        if (process.poll() is not None and not done.exists()) or time.monotonic() > deadline:
            return [], f"couldn't render the chart images, the log is in {log_path}"
        time.sleep(0.05)
    files = json.loads(done.read_text())["files"]
    return files, "opened a window for the user" if show else "rendered off screen, no window for the user"


def _has_display() -> bool:
    if os.environ.get("SSH_CONNECTION"):
        return False
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def _as_answer(specs: list[Spec], columns: dict[str, Column]) -> dict:
    """the final picks, in the same shape --specs reads, so the window shows exactly these"""
    charts = [
        {"kind": s.kind, "x": s.x or "", "y": list(s.y), "color": s.color or "", "title": s.title}
        for s in specs
        if s.kind != "table"
    ]
    labels = [{"column": c.name, "label": c.label} for c in columns.values() if c.label]
    return {"charts": charts, "labels": labels}


def _report(name: str, table: Table, columns: dict[str, Column], figures: list[dict], notes: list[str]) -> str:
    lines = [f"{name}: {plural(len(table.rows), 'row')}, {plural(len(columns), 'column')}", "columns:"]
    for c in columns.values():
        label = f' ("{c.label}")' if c.label else ""
        samples = f", e.g. {', '.join(c.samples)}" if c.samples else ""
        lines.append(f"  {c.name}{label}: {c.kind}, {c.distinct} distinct{samples}")
    lines.append("charts, in the order the user flips through them:")
    lines += [f"{i}. {describe(figure)}" for i, figure in enumerate(figures, 1)]
    lines += notes
    return "\n".join(lines)


def main() -> None:
    server.run("stdio")
