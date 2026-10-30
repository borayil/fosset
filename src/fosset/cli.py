"""fosset <file> or `... | fosset`: read the data, pick charts, open the viewer."""

import argparse
import csv
import os
import sys
import time
import xml.etree.ElementTree as ET

from fosset.charts import build, plural
from fosset.profile import profile
from fosset.readers import MAX_BYTES, MAX_ROWS, Table, detect_format, read
from fosset.recommend import recommend
from fosset.viewer import show


def main(argv: list[str] | None = None) -> None:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(prog="fosset", description="Instantly visualize JSON, CSV or XML data.")
    parser.add_argument("path", nargs="?", help="file to visualize; omit it (or pass -) to read stdin")
    parser.add_argument("--format", choices=["json", "csv", "xml"], help="skip format detection")
    parser.add_argument("--timing", action="store_true", help="print how long each stage took")
    args = parser.parse_args(argv)

    def lap(stage: str) -> None:
        if args.timing:
            print(f"{stage}: {time.perf_counter() - started:.2f}s", file=sys.stderr)

    try:
        text, name = _read_input(args.path)
        table = read(text, args.format or detect_format(text, name))
    except (ValueError, OSError, ET.ParseError, csv.Error) as e:
        sys.exit(f"fosset: {e}")
    if not table.rows:
        sys.exit("fosset: no rows found in the input")
    if table.truncated:
        print(f"fosset: showing the first {MAX_ROWS:,} rows only", file=sys.stderr)
    lap("read")

    figures = charts_for(table)
    lap("charts")

    stem = os.path.splitext(name)[0]
    show(figures, f"fosset — {name} ({plural(len(table.rows), 'row')})", stem, started if args.timing else None)


def charts_for(table: Table) -> list[dict]:
    columns = profile(table)
    return [build(spec, table, columns) for spec in recommend(columns, len(table.rows))]


def _read_input(path: str | None) -> tuple[str, str]:
    if path in (None, "-"):
        if sys.stdin.isatty():
            sys.exit("fosset: give a file path, or pipe data in (e.g. pbpaste | fosset)")
        data, name = sys.stdin.buffer.read(MAX_BYTES + 1), "stdin"
    else:
        with open(path, "rb") as f:
            data, name = f.read(MAX_BYTES + 1), os.path.basename(path)
    if len(data) > MAX_BYTES:
        raise ValueError(f"input is over the {MAX_BYTES // 2**20} MB limit")
    return data.decode("utf-8-sig", errors="replace"), name
