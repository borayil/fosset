import pytest

from fosset import charts
from fosset.charts import build, compact, esc
from fosset.profile import profile
from fosset.readers import Table
from fosset.recommend import Spec


def figure(spec, rows):
    columns = list(dict.fromkeys(k for r in rows for k in r))
    table = Table(columns, rows)
    return build(spec, table, profile(table))


def test_bar_sums_and_ranks_largest_first():
    rows = [{"plan": "free", "n": 1}, {"plan": "pro", "n": 5}, {"plan": "free", "n": 2}]
    fig = figure(Spec("bar", "plan", ("n",), title="N by plan"), rows)
    trace = fig["data"][0]
    assert trace["y"] == ["pro", "free"]
    assert trace["x"] == [5.0, 3.0]
    assert fig["layout"]["title"]["subtitle"]["text"] == "Sum per plan"


def test_bar_averages_rate_like_metrics():
    rows = [{"plan": "free", "avg_latency": 10}, {"plan": "free", "avg_latency": 20}]
    trace = figure(Spec("bar", "plan", ("avg_latency",)), rows)["data"][0]
    assert trace["x"] == [15.0]


def test_bar_counts_rows_without_a_metric():
    rows = [{"c": "DE"}, {"c": "DE"}, {"c": "TR"}]
    assert figure(Spec("bar", "c"), rows)["data"][0]["x"] == [2.0, 1.0]


def test_bar_folds_the_tail_into_other():
    rows = [{"name": f"n{i}", "v": 100 - i} for i in range(25)]
    trace = figure(Spec("bar", "name", ("v",)), rows)["data"][0]
    assert len(trace["y"]) == 20
    assert trace["y"][-1] == "Other (6)"
    assert trace["x"][-1] == sum(100 - i for i in range(19, 25))


def test_line_keeps_an_already_daily_series():
    rows = [{"day": f"2026-10-0{d}", "users": d * 10} for d in range(1, 4)]
    fig = figure(Spec("line", "day", ("users",)), rows)
    trace = fig["data"][0]
    assert trace["x"] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert trace["y"] == [10.0, 20.0, 30.0]
    assert "subtitle" not in fig["layout"]["title"]
    assert fig["layout"]["showlegend"] is False


def test_line_counts_raw_events_per_day_and_fills_empty_days():
    rows = [
        {"at": "2026-10-01T09:15:00Z"},
        {"at": "2026-10-01T17:40:00Z"},
        {"at": "2026-10-04T08:00:00Z"},
    ]
    fig = figure(Spec("line", "at"), rows)
    trace = fig["data"][0]
    assert trace["x"] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    assert trace["y"] == [2.0, 0.0, 0.0, 1.0]
    assert fig["layout"]["title"]["subtitle"]["text"] == "Rows per day"


def test_line_buckets_long_spans_by_week():
    rows = [{"at": f"2026-{m:02d}-15T12:30:00"} for m in range(1, 6)]
    trace = figure(Spec("line", "at"), rows)["data"][0]
    assert trace["x"][0] == "2026-01-12"  # the Monday of that week


def test_line_series_keep_the_biggest_four():
    rows = [{"day": "2026-10-01", "plan": f"p{i}", "n": i} for i in range(6)]
    names = [t["name"] for t in figure(Spec("line", "day", ("n",), "plan"), rows)["data"]]
    assert names == ["p5", "p4", "p3", "p2", "Other (2)"]


def test_scatter_and_hist_skip_missing_values():
    rows = [{"a": 1, "b": 2}, {"a": None, "b": 3}, {"a": 4, "b": "x"}]
    assert figure(Spec("scatter", "a", ("b",)), rows)["data"][0]["x"] == [1.0]
    assert figure(Spec("hist", "a"), rows)["data"][0]["x"] == [1.0, 4.0]


def test_kpi_tiles():
    fig = figure(Spec("kpi", y=("users", "mrr")), [{"users": 12840, "mrr": 99.5}])
    assert [t["value"] for t in fig["data"]] == [12840.0, 99.5]
    assert fig["layout"]["grid"] == {"rows": 1, "columns": 2, "pattern": "independent"}


def test_table_caps_rows():
    rows = [{"i": i} for i in range(600)]
    fig = figure(Spec("table", title="Data"), rows)
    assert len(fig["data"][0]["cells"]["values"][0]) == 500
    assert fig["layout"]["title"]["subtitle"]["text"] == "First 500 of 600 rows"


def test_columns_are_parsed_once_across_charts(monkeypatch):
    calls = []
    real = charts.to_datetime
    monkeypatch.setattr(charts, "to_datetime", lambda v: calls.append(v) or real(v))
    rows = [{"at": f"2026-10-0{d}T10:30:00", "n": d} for d in range(1, 6)]
    table = Table(["at", "n"], rows)
    columns = profile(table)
    build(Spec("line", "at"), table, columns)
    build(Spec("line", "at", ("n",)), table, columns)
    assert len(calls) == len(rows)


def test_llm_labels_and_keys():
    rows = [{"plan": "free", "mrr_eur": 1}, {"plan": "pro", "mrr_eur": 2}]
    table = Table(["plan", "mrr_eur"], rows)
    columns = profile(table)
    columns["mrr_eur"].label = "MRR (€)"
    fig = build(Spec("bar", "plan", ("mrr_eur",)), table, columns)
    assert fig["layout"]["xaxis"]["title"]["text"] == "MRR (€)"
    assert fig["key"] == "bar|plan|mrr_eur|"


def test_labels_from_data_are_escaped():
    rows = [{"name": "<b>x</b>", "v": 1}, {"name": "y", "v": 2}]
    fig = figure(Spec("bar", "name", ("v",), title="<i>"), rows)
    assert "&lt;b&gt;x&lt;/b&gt;" in fig["data"][0]["y"]
    assert fig["layout"]["title"]["text"] == "&lt;i&gt;"
    assert esc("a & b") == "a &amp; b"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.004, "0.004"), (12, "12"), (1284, "1,284"), (12.5, "12.5"), (12900, "12.9K"), (4_200_000, "4.2M"),
     (2_000_000_000, "2B"), (-15000, "-15K")],
)
def test_compact(value, expected):
    assert compact(value) == expected
