from fosset.profile import Column, profile
from fosset.readers import Table
from fosset.recommend import Spec, human, recommend, validate


def specs_for(rows):
    columns = list(dict.fromkeys(k for r in rows for k in r))
    return recommend(profile(Table(columns, rows)), len(rows))


def test_daily_metric_by_plan_leads_with_a_line():
    rows = [
        {"day": f"2026-10-{d:02d}", "plan": plan, "signups": d}
        for d in range(1, 11)
        for plan in ("free", "pro")
    ]
    specs = specs_for(rows)
    assert specs[0] == Spec("line", "day", ("signups",), "plan", "Signups over time by plan")
    assert specs[1] == Spec("bar", "plan", ("signups",), title="Signups by plan")
    assert specs[-1].kind == "table"
    assert [s.kind for s in specs].count("hist") == 0  # one row per day and plan is not raw data


def test_single_row_becomes_kpi_tiles():
    specs = specs_for([{"total_users": 10, "active": 3, "label": "x"}])
    assert specs == [Spec("kpi", y=("total_users", "active"), title="Summary"), Spec("table", title="Data")]


def test_raw_events_get_counts_and_a_histogram():
    rows = [
        {"order_id": i, "created_at": f"2026-10-{i % 28 + 1:02d}T10:{i % 60:02d}:00Z",
         "status": ["paid", "refunded"][i % 2], "amount": i}
        for i in range(60)
    ]
    kinds = [(s.kind, s.y) for s in specs_for(rows)]
    assert kinds[0] == ("line", ())  # rows over time comes first for event data
    assert ("bar", ()) in kinds
    assert ("hist", ()) in kinds


def test_one_row_per_category():
    rows = [{"feature": f, "calls": i * 10, "latency": i} for i, f in enumerate(["a", "b", "c", "d"])]
    assert [s.kind for s in specs_for(rows)] == ["bar", "bar", "scatter", "table"]


def test_only_categories_counts_rows():
    rows = [{"country": c} for c in ["DE", "DE", "TR", "US"]]
    assert specs_for(rows)[0] == Spec("bar", "country", title="Rows per country")


def test_unusable_data_still_gets_the_table():
    assert specs_for([{"note": "x" * 50}, {"note": "y" * 50}]) == [Spec("table", title="Data")]


COLUMNS = {
    "day": Column("day", "datetime", 10, 10),
    "plan": Column("plan", "category", 10, 2),
    "users": Column("users", "number", 10, 10),
    "revenue": Column("revenue", "number", 10, 10),
    "id": Column("id", "id", 10, 10),
}


def test_validate_accepts_specs_that_fit_the_columns():
    assert validate(Spec("line", "day", ("users",), "plan"), COLUMNS)
    assert validate(Spec("line", "day"), COLUMNS)
    assert validate(Spec("bar", "plan", ("revenue",)), COLUMNS)
    assert validate(Spec("scatter", "users", ("revenue",)), COLUMNS)
    assert validate(Spec("hist", "users"), COLUMNS)
    assert validate(Spec("kpi", y=("users", "revenue")), COLUMNS)
    assert validate(Spec("table"), COLUMNS)


def test_validate_rejects_specs_that_do_not_fit():
    assert not validate(Spec("line", "day", ("nope",)), COLUMNS)  # missing column
    assert not validate(Spec("line", "plan", ("users",)), COLUMNS)  # x is not time or number
    assert not validate(Spec("bar", "plan", ("users", "revenue")), COLUMNS)  # one metric per bar chart
    assert not validate(Spec("bar", "plan", ("id",)), COLUMNS)  # ids are not metrics
    assert not validate(Spec("line", "day", ("users",), "users"), COLUMNS)  # color must be a category
    assert not validate(Spec("scatter", "users"), COLUMNS)
    assert not validate(Spec("kpi"), COLUMNS)
    assert not validate(Spec("pie", "plan"), COLUMNS)


def test_human():
    assert human("signup_count") == "Signup count"
    assert human("stats.users", capital=False) == "stats users"
