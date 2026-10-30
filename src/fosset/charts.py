"""turns a chart spec plus the table into a plotly figure.

colors are left out on purpose, the viewer adds them for light or dark mode.
"""

import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from fosset.profile import Column, to_datetime, to_number
from fosset.readers import Table
from fosset.recommend import Spec, human

MAX_BARS = 20
MAX_LINES = 4
MAX_TABLE_ROWS = 500
MAX_LABEL = 40
# more distinct times than this and we bucket them by hour, day, week or month
MAX_POINTS = 500
WEBGL_POINTS = 5000
MEAN_WORDS = {"avg", "average", "mean", "rate", "ratio", "pct", "percent", "percentage", "share"}


def build(spec: Spec, table: Table, columns: dict[str, Column]) -> dict:
    builders = {
        "line": _line,
        "bar": _bar,
        "scatter": _scatter,
        "hist": _hist,
        "kpi": _kpi,
        "table": _table,
    }
    return builders[spec.kind](spec, table, columns)


def _line(spec, table, columns):
    x = spec.x
    is_date = columns[x].kind == "datetime"
    parse_x = to_datetime if is_date else to_number
    y = spec.y[0] if spec.y else None
    agg = _agg(y)

    xs = _column(table, x, parse_x)
    values = _column(table, y, to_number) if y else None
    series = _column(table, spec.color, _label) if spec.color else None
    keep = [i for i, xv in enumerate(xs) if xv is not None and (values is None or values[i] is not None)]

    # bucket raw timestamps and really long series, but leave daily or hourly
    # series that are already rolled up alone
    unit = None
    if is_date and keep:
        raw_times = any(xs[i].minute or xs[i].second or xs[i].microsecond for i in keep)
        if y is None or raw_times or len({xs[i] for i in keep}) > MAX_POINTS:
            unit = _time_unit(min(xs[i] for i in keep), max(xs[i] for i in keep))
            parsed = xs
            xs = _cached(table, ("bucket", x, unit), lambda: [None if v is None else _truncate(v, unit) for v in parsed])

    points = [(series[i] if series else "", xs[i], values[i] if values else 1.0) for i in keep]

    # an empty bucket is a real zero for sums and counts, so draw it instead of
    # connecting across. for averages we just don't know, so leave a gap
    buckets = _bucket_range(min(p[1] for p in points), max(p[1] for p in points), unit) if unit else None

    data, merged = [], False
    for name, pts, is_other in _fold(points, MAX_LINES):
        groups = defaultdict(list)
        for _, xv, v in pts:
            groups[xv].append(v)
        merged = merged or any(len(vs) > 1 for vs in groups.values())
        xs = buckets or sorted(groups)
        empty = 0.0 if agg == "sum" else None
        trace = {
            "type": "scattergl" if len(xs) > WEBGL_POINTS else "scatter",
            "mode": "lines+markers" if len(xs) <= 30 else "lines",
            "name": esc(name),
            "x": [_fmt_x(v) for v in xs],
            "y": [_aggregate(groups[k], agg) if k in groups else empty for k in xs],
            "hovertemplate": "%{y:,.2~f}",
        }
        if is_other:
            trace["meta"] = "other"
        data.append(trace)

    if y is None:
        subtitle = f"Rows per {unit}" if unit else ""
    else:
        subtitle = f"{_agg_word(agg)} per {unit or 'point'}" if merged else ""
    return _figure(
        spec.title,
        data,
        subtitle,
        hovermode="x unified",
        xaxis={"showspikes": True, "spikemode": "across", "spikesnap": "cursor"},
        yaxis={"title": {"text": esc(human(y)) if y else "Rows"}, "rangemode": "tozero"},
    )


def _bar(spec, table, columns):
    y = spec.y[0] if spec.y else None
    agg = _agg(y)
    keys = _column(table, spec.x, _key)
    values = _column(table, y, to_number) if y else None
    groups = defaultdict(list)
    for i, key in enumerate(keys):
        v = 1.0 if values is None else values[i]
        if key is not None and v is not None:
            groups[key].append(v)

    totals = {k: _aggregate(vs, agg) for k, vs in groups.items()}
    ranked = sorted(totals, key=totals.get, reverse=True)
    bars = [(k, totals[k]) for k in ranked]
    subtitle = [f"{_agg_word(agg)} per {human(spec.x).lower()}"] if y and any(len(vs) > 1 for vs in groups.values()) else []
    if len(ranked) > MAX_BARS:
        rest = ranked[MAX_BARS - 1:]
        bars = bars[:MAX_BARS - 1]
        bars.append((f"Other ({len(rest)})", _aggregate([v for k in rest for v in groups[k]], agg)))
        subtitle.append(f"top {MAX_BARS - 1} + other")

    values = [v for _, v in bars]
    data = [{
        "type": "bar",
        "orientation": "h",
        "y": [esc(_short(k)) for k, _ in bars],
        "x": values,
        "text": [compact(v) for v in values],
        "textposition": "outside",
        "cliponaxis": False,
        "hovertemplate": "<b>%{x:,.2~f}</b>  %{y}<extra></extra>",
    }]
    return _figure(
        spec.title,
        data,
        " · ".join(subtitle),
        hovermode="closest",
        xaxis={"title": {"text": esc(human(y)) if y else "Rows"}},
        yaxis={"type": "category", "autorange": "reversed", "automargin": True},
    )


def _scatter(spec, table, columns):
    x, y = spec.x, spec.y[0]
    pairs = zip(_column(table, x, to_number), _column(table, y, to_number))
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    data = [{
        "type": "scattergl" if len(pairs) > WEBGL_POINTS else "scatter",
        "mode": "markers",
        "x": [a for a, _ in pairs],
        "y": [b for _, b in pairs],
        "hovertemplate": f"{esc(human(x))} %{{x:,.2~f}}<br>{esc(human(y))} %{{y:,.2~f}}<extra></extra>",
    }]
    return _figure(
        spec.title,
        data,
        hovermode="closest",
        xaxis={"title": {"text": esc(human(x))}},
        yaxis={"title": {"text": esc(human(y))}},
    )


def _hist(spec, table, columns):
    data = [{
        "type": "histogram",
        "x": [v for v in _column(table, spec.x, to_number) if v is not None],
        "hovertemplate": "%{x}<br><b>%{y:,}</b> rows<extra></extra>",
    }]
    return _figure(
        spec.title,
        data,
        hovermode="closest",
        xaxis={"title": {"text": esc(human(spec.x))}},
        yaxis={"title": {"text": "Rows"}},
    )


def _kpi(spec, table, columns):
    row = table.rows[0]
    tiles = [(name, to_number(row.get(name))) for name in spec.y]
    tiles = [(name, v) for name, v in tiles if v is not None]
    n_cols = min(len(tiles), 4)
    data = [
        {
            "type": "indicator",
            "mode": "number",
            "value": v,
            "title": {"text": esc(human(name))},
            "number": {"valueformat": ",.2~f" if abs(v) < 10_000 else ".3~s"},
            "domain": {"row": i // n_cols, "column": i % n_cols},
        }
        for i, (name, v) in enumerate(tiles)
    ]
    grid = {"rows": math.ceil(len(tiles) / n_cols), "columns": n_cols, "pattern": "independent"}
    return _figure(spec.title, data, grid=grid)


def _table(spec, table, columns):
    rows = table.rows[:MAX_TABLE_ROWS]
    if len(table.rows) > len(rows):
        subtitle = f"First {len(rows):,} of {len(table.rows):,} rows"
    else:
        subtitle = plural(len(rows), "row")
    data = [{
        "type": "table",
        "header": {"values": [esc(c) for c in table.columns]},
        "cells": {"values": [[_cell(r.get(c)) for r in rows] for c in table.columns]},
    }]
    return _figure(spec.title, data, subtitle)


# helpers


def _column(table, name, parse):
    """parse a column once and reuse it for every chart, parsing is most of the work"""
    return _cached(table, (name, parse), lambda: [parse(row.get(name)) for row in table.rows])


def _cached(table, key, compute):
    if key not in table.cache:
        table.cache[key] = compute()
    return table.cache[key]


def _figure(title, data, subtitle="", **layout):
    title_layout = {"text": esc(title)}
    if subtitle:
        title_layout["subtitle"] = {"text": esc(subtitle)}
    return {"data": data, "layout": {"title": title_layout, "showlegend": len(data) > 1, **layout}}


def _fold(points, limit):
    """keep the `limit` biggest series and lump the rest into one "Other" series"""
    by_series = defaultdict(list)
    for p in points:
        by_series[p[0]].append(p)
    ranked = sorted(by_series, key=lambda s: sum(abs(p[2]) for p in by_series[s]), reverse=True)
    out = [(name, by_series[name], False) for name in ranked[:limit]]
    rest = ranked[limit:]
    if rest:
        out.append((f"Other ({len(rest)})", [p for name in rest for p in by_series[name]], True))
    return out


def _agg(metric: str | None) -> str:
    """averages, rates and shares get averaged, everything else gets summed"""
    if metric is None:
        return "sum"
    words = re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", metric).lower())
    return "mean" if MEAN_WORDS.intersection(words) else "sum"


def _agg_word(agg: str) -> str:
    return "Average" if agg == "mean" else "Sum"


def _aggregate(values: list[float], agg: str) -> float:
    return statistics.fmean(values) if agg == "mean" else math.fsum(values)


def _time_unit(lo: datetime, hi: datetime) -> str:
    span = hi - lo
    if span <= timedelta(days=2):
        return "hour"
    if span <= timedelta(days=60):
        return "day"
    if span <= timedelta(days=366):
        return "week"
    return "month"


def _truncate(dt: datetime, unit: str) -> datetime:
    if unit == "hour":
        return datetime(dt.year, dt.month, dt.day, dt.hour)
    if unit == "month":
        return datetime(dt.year, dt.month, 1)
    day = datetime(dt.year, dt.month, dt.day)
    return day - timedelta(days=day.weekday()) if unit == "week" else day


def _bucket_range(lo: datetime, hi: datetime, unit: str) -> list[datetime]:
    out, current = [], lo
    while current <= hi:
        out.append(current)
        if unit == "month":
            current = current.replace(year=current.year + current.month // 12, month=current.month % 12 + 1)
        else:
            current += {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(weeks=1)}[unit]
    return out


def _fmt_x(value):
    if isinstance(value, datetime):
        if value.time() == datetime.min.time():
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    return value


def _label(value) -> str:
    return "(empty)" if value in (None, "") else str(value)


def _key(value) -> str | None:
    return None if value in (None, "") else str(value)


def _short(text: str) -> str:
    return text if len(text) <= MAX_LABEL else text[:MAX_LABEL - 1] + "…"


def _cell(value) -> str:
    return "" if value is None else esc(_short(str(value)))


def plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def esc(text) -> str:
    """plotly renders some html in text, so escape anything that comes from the data"""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def compact(value: float) -> str:
    """short number labels like 1,284 or 12.9K or 4.2M"""
    a = abs(value)
    if a < 1:
        return f"{value:.3g}"
    if a < 10_000:
        return f"{int(value):,}" if value == int(value) else f"{value:,.2f}".rstrip("0").rstrip(".")
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{value / div:.1f}".rstrip("0").rstrip(".") + suffix
