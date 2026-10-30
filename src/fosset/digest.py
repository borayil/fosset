"""a short text version of each chart, so claude can reason about the actual numbers
and not just eyeball the picture"""

import html
import statistics

from fosset.charts import aggregation, compact

TOP_BARS = 5


def describe(figure: dict) -> str:
    """one line of what the chart is, then the numbers worth knowing"""
    title = html.unescape(figure["layout"]["title"]["text"])
    return f"{title} [{_shape(figure.get('key', ''))}]\n{_numbers(figure)}"


def _shape(key: str) -> str:
    kind, x, y, color = (key.split("|") + ["", "", "", ""])[:4]
    parts = [kind] + [f"{name}={value}" for name, value in (("x", x), ("y", y), ("color", color)) if value]
    return " ".join(parts)


def _numbers(figure: dict) -> str:
    data = figure["data"]
    kind = data[0]["type"] if data else ""
    if kind in ("scatter", "scattergl"):
        return _line(data) if data[0]["mode"].startswith("lines") else _scatter(data[0])
    if kind == "bar":
        return _bar(data[0], (figure.get("key", "").split("|") + ["", "", ""])[2])
    if kind == "histogram":
        return _hist(data[0])
    if kind == "indicator":
        return "  " + ", ".join(f"{html.unescape(t['title']['text'])} {compact(t['value'])}" for t in data)
    if kind == "table":
        cells = data[0]["cells"]["values"]
        return f"  {len(cells[0]) if cells else 0} rows shown, {len(cells)} columns"
    return "  (nothing to summarize)"


def _line(data: list[dict]) -> str:
    lines = []
    for trace in data:
        points = [(x, y) for x, y in zip(trace["x"], trace["y"]) if y is not None]
        if not points:
            continue
        low = min(points, key=lambda p: p[1])
        high = max(points, key=lambda p: p[1])
        name = html.unescape(trace["name"]) or "values"
        lines.append(
            f"  {name}: {len(points)} points, from {compact(points[0][1])} ({points[0][0]}) "
            f"to {compact(points[-1][1])} ({points[-1][0]}), low {compact(low[1])} ({low[0]}), "
            f"high {compact(high[1])} ({high[0]})"
        )
    return "\n".join(lines) or "  (no points)"


def _bar(trace: dict, metric: str) -> str:
    bars = list(zip(trace["y"], trace["x"]))
    top = ", ".join(f"{html.unescape(label)} {compact(value)}" for label, value in bars[:TOP_BARS])
    text = f"  {len(bars)} bars, biggest first: {top}"
    if aggregation(metric or None) == "sum":  # a total of averages or rates means nothing
        text += f". total {compact(sum(value for _, value in bars))}"
    return text


def _hist(trace: dict) -> str:
    values = trace["x"]
    if not values:
        return "  (no values)"
    return (
        f"  {len(values)} values, min {compact(min(values))}, median {compact(statistics.median(values))}, "
        f"max {compact(max(values))}"
    )


def _scatter(trace: dict) -> str:
    xs, ys = trace["x"], trace["y"]
    text = f"  {len(xs)} points"
    try:
        text += f", correlation {statistics.correlation(xs, ys):.2f}"
    except statistics.StatisticsError:
        pass  # fewer than two points, or one side never changes
    return text
