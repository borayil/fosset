from fosset.charts import build
from fosset.digest import describe
from fosset.profile import profile
from fosset.readers import Table
from fosset.recommend import Spec


def digest_of(spec, rows):
    columns = list(dict.fromkeys(k for r in rows for k in r))
    table = Table(columns, rows)
    return describe(build(spec, table, profile(table)))


def test_line_digest_per_series():
    rows = [{"day": f"2026-10-0{d}", "plan": plan, "n": d * (2 if plan == "pro" else 1)}
            for d in range(1, 5) for plan in ("free", "pro")]
    text = digest_of(Spec("line", "day", ("n",), "plan", "N over time by plan"), rows)
    assert text.startswith("N over time by plan [line x=day y=n color=plan]")
    assert "pro: 4 points, from 2 (2026-10-01) to 8 (2026-10-04), low 2 (2026-10-01), high 8 (2026-10-04)" in text
    assert "free: 4 points" in text


def test_bar_digest_lists_the_biggest_and_the_total():
    rows = [{"c": f"c{i}", "v": i} for i in range(1, 8)]
    text = digest_of(Spec("bar", "c", ("v",), title="V by c"), rows)
    assert "7 bars, biggest first: c7 7, c6 6, c5 5, c4 4, c3 3. total 28" in text


def test_bar_digest_skips_the_total_for_averages():
    rows = [{"c": "a", "avg_ms": 10}, {"c": "a", "avg_ms": 20}, {"c": "b", "avg_ms": 5}]
    text = digest_of(Spec("bar", "c", ("avg_ms",), title="Latency"), rows)
    assert "biggest first: a 15, b 5" in text
    assert "total" not in text


def test_bar_digest_skips_the_total_for_one_row_per_category_averages_too():
    rows = [{"feature": "search", "avg_latency_ms": 85}, {"feature": "login", "avg_latency_ms": 46}]
    assert "total" not in digest_of(Spec("bar", "feature", ("avg_latency_ms",), title="Latency"), rows)


def test_hist_scatter_kpi_and_table_digests():
    rows = [{"a": i, "b": i * 2} for i in range(1, 6)]
    assert "5 values, min 1, median 3, max 5" in digest_of(Spec("hist", "a", title="A"), rows)
    assert "5 points, correlation 1.00" in digest_of(Spec("scatter", "a", ("b",), title="B vs a"), rows)
    assert "rows shown, 2 columns" in digest_of(Spec("table", title="Data"), rows)
    kpi = digest_of(Spec("kpi", y=("a", "b"), title="Summary"), [{"a": 12840, "b": 3}])
    assert "A 12.8K, B 3" in kpi


def test_scatter_with_a_flat_side_has_no_correlation():
    rows = [{"a": i, "b": 1} for i in range(5)]
    text = digest_of(Spec("scatter", "a", ("b",), title="flat"), rows)
    assert "5 points" in text and "correlation" not in text
