"""figures out what kind of stuff each column holds"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fosset.numbers import readers, to_number
from fosset.readers import Table

# only look at the first rows so big files stay fast
SAMPLE_ROWS = 5000
# a column gets a kind when 90% of its values fit it
MATCH_SHARE = 0.9
TEXT_MIN_LENGTH = 40
SAMPLE_COUNT = 3
SAMPLE_LENGTH = 40

_YEAR_MONTH = re.compile(r"^\d{4}-\d{2}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_DATE_FORMATS = ("%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d")


@dataclass
class Column:
    name: str
    kind: str  # number | datetime | category | text | id | empty
    count: int  # values that aren't empty, in the sample
    distinct: int
    samples: list[str] = field(default_factory=list)  # a few values, so the llm gets what the column is
    label: str | None = None  # a nicer name from the llm, like "MRR (€)"
    # how a number column gets read, plain or written out for people like "21.985.979 ₺"
    parse: Callable[[object], float | None] = field(default=to_number, repr=False, compare=False)

    @property
    def unique(self) -> bool:
        return self.count > 0 and self.distinct == self.count


def profile(table: Table) -> dict[str, Column]:
    sample = table.rows[:SAMPLE_ROWS]
    columns = {}
    for name in table.columns:
        values = [r.get(name) for r in sample]
        values = [v for v in values if v is not None and v != ""]
        distinct = len({str(v) for v in values})
        samples = list(dict.fromkeys(str(v)[:SAMPLE_LENGTH] for v in values[:200]))[:SAMPLE_COUNT]
        parse = _number_reader(values, table.separators)
        kind = _kind(name, values, parse is not None)
        columns[name] = Column(name, kind, len(values), distinct, samples, parse=parse or to_number)
    return columns


def _number_reader(values: list, separators: tuple[str, str]) -> Callable | None:
    """the first way of reading numbers that fits the column, if any does"""
    return next((parse for parse in readers(separators) if values and _share(values, parse) >= MATCH_SHARE), None)


def _kind(name: str, values: list, numbers: bool) -> str:
    if not values:
        return "empty"
    if all(isinstance(v, bool) or str(v).lower() in ("true", "false") for v in values):
        return "category"
    if _is_id_name(name) or _share(values, lambda v: _UUID.match(str(v))) >= MATCH_SHARE:
        return "id"
    if numbers:
        return "number"
    if _share(values, to_datetime) >= MATCH_SHARE:
        return "datetime"
    if sum(len(str(v)) for v in values) / len(values) > TEXT_MIN_LENGTH:
        return "text"
    return "category"


def _share(values: list, test) -> float:
    return sum(test(v) is not None for v in values) / len(values)


def _is_id_name(name: str) -> bool:
    lower = name.lower()
    return lower in ("id", "uuid") or lower.endswith(("_id", ".id", "_uuid")) or name.endswith("Id")


def to_datetime(value) -> datetime | None:
    """parse common date strings into plain utc datetimes, which is what the charts want"""
    if not isinstance(value, str) or len(value) < 7:
        return None
    text = value.strip()
    if _YEAR_MONTH.match(text):
        text += "-01"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                pass
        else:
            return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
