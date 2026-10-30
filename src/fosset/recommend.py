"""picks the charts that make the most sense for a table and checks specs against it.

best guess comes first.
"""

from dataclasses import dataclass

from fosset.profile import Column

MAX_CHARTS = 8
MAX_METRICS = 4
MAX_SERIES_CATEGORIES = 20
MAX_KPIS = 12


@dataclass(frozen=True)
class Spec:
    kind: str  # line | bar | scatter | hist | kpi | table
    x: str | None = None
    y: tuple[str, ...] = ()  # empty on line/bar means "count rows"
    color: str | None = None
    title: str = ""


def recommend(columns: dict[str, Column], n_rows: int) -> list[Spec]:
    cols = list(columns.values())
    numbers = [c.name for c in cols if c.kind == "number"]
    dates = [c.name for c in cols if c.kind == "datetime"]
    categories = [c for c in cols if c.kind == "category" and c.distinct > 1]
    metrics = numbers[:MAX_METRICS]
    # an id column means each row is one thing (an order, an event), so counting rows actually means something
    entity_rows = any(c.kind == "id" for c in cols)

    specs = []
    if n_rows == 1:
        if numbers:
            specs.append(Spec("kpi", y=tuple(numbers[:MAX_KPIS]), title="Summary"))
    else:
        if dates:
            x = dates[0]
            series = next(
                (c.name for c in categories if not c.unique and c.distinct <= MAX_SERIES_CATEGORIES),
                None,
            )
            by = f" by {human(series, capital=False)}" if series else ""
            if entity_rows or not metrics:
                specs.append(Spec("line", x, (), series, f"Rows over time{by}"))
            for y in metrics:
                specs.append(Spec("line", x, (y,), series, f"{human(y)} over time{by}"))

        if categories:
            dim = categories[0]
            for y in metrics:
                specs.append(Spec("bar", dim.name, (y,), title=f"{human(y)} by {human(dim.name, capital=False)}"))
            if entity_rows or not metrics:
                for c in categories[:3]:
                    if not c.unique:
                        specs.append(Spec("bar", c.name, title=f"Rows per {human(c.name, capital=False)}"))

        if len(metrics) >= 2 and not dates:
            x, y = metrics[0], metrics[1]
            specs.append(Spec("scatter", x, (y,), title=f"{human(y)} vs {human(x, capital=False)}"))

        # histograms only make sense on raw rows, not one row per category or per day
        raw_rows = entity_rows or not categories or not categories[0].unique
        if metrics and n_rows >= 30 and raw_rows and (entity_rows or not dates):
            specs.append(Spec("hist", metrics[0], title=f"Distribution of {human(metrics[0], capital=False)}"))

    specs = [s for s in specs if validate(s, columns)][:MAX_CHARTS]
    specs.append(Spec("table", title="Data"))
    return specs


def validate(spec: Spec, columns: dict[str, Column]) -> bool:
    """the constraint check: every column has to exist and fit the chart type"""
    named = [n for n in (spec.x, spec.color, *spec.y) if n is not None]
    if any(n not in columns for n in named):
        return False

    def kind(name):
        return columns[name].kind

    if spec.color is not None and kind(spec.color) != "category":
        return False
    all_numbers = all(kind(y) == "number" for y in spec.y)
    one_metric = len(spec.y) <= 1 and all_numbers
    if spec.kind == "line":
        return spec.x is not None and kind(spec.x) in ("datetime", "number") and one_metric
    if spec.kind == "bar":
        return spec.x is not None and kind(spec.x) == "category" and one_metric
    if spec.kind == "scatter":
        return spec.x is not None and kind(spec.x) == "number" and len(spec.y) == 1 and all_numbers
    if spec.kind == "hist":
        return spec.x is not None and kind(spec.x) == "number"
    if spec.kind == "kpi":
        return bool(spec.y) and all_numbers
    return spec.kind == "table"


def human(name: str, capital: bool = True) -> str:
    """turns signup_count into "Signup count", or "signup count" in the middle of a title"""
    text = name.replace("_", " ").replace(".", " ").strip()
    return text[:1].upper() + text[1:] if capital else text
