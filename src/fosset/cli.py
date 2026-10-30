"""fosset <file>, or pipe stuff into it. reads the data, picks charts, opens the window"""

import argparse
import csv
import os
import sys
import time
import xml.etree.ElementTree as ET

from fosset import llm
from fosset.charts import build, plural
from fosset.profile import Column, profile
from fosset.readers import MAX_BYTES, MAX_ROWS, Table, detect_format, read
from fosset.recommend import Spec, merge, recommend
from fosset.viewer import show


def main(argv: list[str] | None = None) -> None:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(prog="fosset", description="throw json, csv or xml at it and get charts")
    parser.add_argument("path", nargs="?", help="the file to chart, leave it out (or pass -) to read from a pipe")
    parser.add_argument("--format", choices=["json", "csv", "xml"], help="skip guessing the format")
    parser.add_argument("--no-llm", action="store_true", help="skip the llm and just use the rules")
    parser.add_argument("--timing", action="store_true", help="print how long each step took")
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
        sys.exit("fosset: couldn't find any rows in there")
    if table.truncated:
        print(f"fosset: that's a lot of rows, only showing the first {MAX_ROWS:,}", file=sys.stderr)
    lap("read")

    columns = profile(table)
    n_rows = len(table.rows)
    rules = recommend(columns, n_rows)
    specs, status, later = rules, "", None

    config = None if args.no_llm else _llm_config()
    if config and llm.worth_asking(columns):
        key = llm.fingerprint(columns, n_rows, config)
        answer = llm.cached(key)
        if answer:
            specs = _use_answer(answer, columns, n_rows, rules)
            status = f"picked by {config.model} (cached)"
        else:
            status = f"asking {config.model}…"

            def later():
                return _ask_llm(config, key, table, columns, rules, name, args.timing)

    figures = [build(spec, table, columns) for spec in specs]
    lap("charts")

    stem = os.path.splitext(name)[0]
    title = f"fosset · {name} · {plural(n_rows, 'row')}"
    show(figures, title, stem, started if args.timing else None, status=status, later=later)


def charts_for(table: Table) -> list[dict]:
    """rule picks only, no llm"""
    columns = profile(table)
    return [build(spec, table, columns) for spec in recommend(columns, len(table.rows))]


def _llm_config() -> llm.Config | None:
    try:
        return llm.load_config()
    except (ValueError, OSError) as e:
        print(f"fosset: ignoring the llm config, {e}", file=sys.stderr)
        return None


def _use_answer(answer: dict, columns: dict[str, Column], n_rows: int, rules: list[Spec]) -> list[Spec]:
    specs, labels = llm.to_specs(answer, columns, n_rows)
    for name, label in labels.items():
        columns[name].label = label
    return merge(specs, rules)


def _ask_llm(config, key, table, columns, rules, name, timing) -> tuple[list[dict] | None, str]:
    """runs in the background while the window is already showing the rule picks"""
    asked = time.perf_counter()
    try:
        answer = llm.ask(config, llm.summarize(columns, len(table.rows), name))
    except llm.LLMError as e:
        print(f"fosset: llm didn't work out, {e}", file=sys.stderr)
        return None, "llm didn't work out, these are the rule picks"
    if timing:
        print(f"llm answered in {time.perf_counter() - asked:.2f}s", file=sys.stderr)
    try:
        llm.remember(key, answer)
    except OSError:
        pass  # no cache this time, not a big deal
    specs = _use_answer(answer, columns, len(table.rows), rules)
    return [build(spec, table, columns) for spec in specs], f"picked by {config.model}"


def _read_input(path: str | None) -> tuple[str, str]:
    if path in (None, "-"):
        if sys.stdin.isatty():
            sys.exit("fosset: gimme a file, or pipe something in (like pbpaste | fosset)")
        data, name = sys.stdin.buffer.read(MAX_BYTES + 1), "stdin"
    else:
        with open(path, "rb") as f:
            data, name = f.read(MAX_BYTES + 1), os.path.basename(path)
    if len(data) > MAX_BYTES:
        raise ValueError(f"that's over {MAX_BYTES // 2**20} MB, fosset keeps it small so it stays fast")
    return data.decode("utf-8-sig", errors="replace"), name
