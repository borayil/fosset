"""fosset <file>, or pipe stuff into it. reads the data, picks charts, opens the window"""

import argparse
import csv
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from fosset import llm
from fosset.charts import build, plural
from fosset.profile import profile
from fosset.readers import MAX_BYTES, MAX_ROWS, Table, decode, detect_format, load, read
from fosset.recommend import recommend
from fosset.viewer import show, write_html


def main(argv: list[str] | None = None) -> None:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(prog="fosset", description="throw json, csv or xml at it and get charts")
    parser.add_argument("path", nargs="?", help="the file to chart, leave it out (or pass -) to read from a pipe")
    parser.add_argument("--format", choices=["json", "csv", "xml"], help="skip guessing the format")
    parser.add_argument("--title", help="what to call the data in the window title")
    parser.add_argument("--specs", metavar="FILE", help="use these chart picks ({charts, labels} json) instead of guessing")
    parser.add_argument("--no-llm", action="store_true", help="skip the llm and just use the rules")
    parser.add_argument("--png", metavar="DIR", help="also save every chart as a png in DIR")
    parser.add_argument("--headless", action="store_true", help="don't show a window, just save the pngs (needs --png)")
    parser.add_argument("--html", metavar="FILE", help="write a standalone page you can open in any browser, no window")
    parser.add_argument("--timing", action="store_true", help="print how long each step took")
    args = parser.parse_args(argv)
    if args.headless and not args.png:
        parser.error("--headless needs --png, otherwise there's nothing to show or save")

    def lap(stage: str) -> None:
        if args.timing:
            print(f"{stage}: {time.perf_counter() - started:.2f}s", file=sys.stderr)

    try:
        text, name = _read_input(args.path)
        table = read(text, args.format or detect_format(text, name))
        answer = json.loads(Path(args.specs).read_text()) if args.specs else None
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
    # the llm can only swap picks into a window that stays open
    live_window = not (args.html or args.headless)

    if answer is not None:
        specs = llm.apply_answer(answer, columns, n_rows, rules)
    else:
        config = None if args.no_llm else _llm_config()
        if config and llm.worth_asking(columns):
            key = llm.fingerprint(columns, n_rows, config)
            cached = llm.cached(key)
            if cached:
                specs = llm.apply_answer(cached, columns, n_rows, rules)
                status = f"picked by {config.model} (cached)"
            elif live_window:
                status = f"asking {config.model}…"

                def later():
                    return _ask_llm(config, key, table, columns, rules, name, args.timing)

    figures = [build(spec, table, columns) for spec in specs]
    lap("charts")

    if args.html:
        write_html(figures, Path(args.html), status)
        print(args.html)
        return
    title = f"fosset · {args.title or name} · {plural(n_rows, 'row')}"
    show(
        figures,
        title,
        os.path.splitext(name)[0],
        started if args.timing else None,
        status=status,
        later=later,
        png_dir=Path(args.png) if args.png else None,
        headless=args.headless,
    )


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
    specs = llm.apply_answer(answer, columns, len(table.rows), rules)
    return [build(spec, table, columns) for spec in specs], f"picked by {config.model}"


def _read_input(path: str | None) -> tuple[str, str]:
    if path not in (None, "-"):
        return load(path)
    if sys.stdin.isatty():
        sys.exit("fosset: gimme a file, or pipe something in (like pbpaste | fosset)")
    return decode(sys.stdin.buffer.read(MAX_BYTES + 1)), "stdin"
