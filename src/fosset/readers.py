"""reads json, csv or xml and flattens it into plain rows"""

import csv
import io
import json
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# limits so the whole thing stays fast
MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 200_000

EXTENSIONS = {
    ".json": "json",
    ".jsonl": "json",
    ".ndjson": "json",
    ".csv": "csv",
    ".tsv": "csv",
    ".xml": "xml",
}


@dataclass
class Table:
    columns: list[str]
    rows: list[dict]
    truncated: bool = False
    # parsed columns, shared by all the charts built from this table
    cache: dict = field(default_factory=dict, repr=False, compare=False)


def load(path: str) -> tuple[str, str]:
    """read a file as text, returning (text, file name)"""
    with open(path, "rb") as f:
        return decode(f.read(MAX_BYTES + 1)), Path(path).name


def decode(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError(f"that's over {MAX_BYTES // 2**20} MB, fosset keeps it small so it stays fast")
    return data.decode("utf-8-sig", errors="replace")


def detect_format(text: str, filename: str | None = None) -> str:
    """go by the file extension if we know it, otherwise peek at the content"""
    if filename:
        fmt = EXTENSIONS.get(Path(filename).suffix.lower())
        if fmt:
            return fmt
    head = text.lstrip()[:1]
    if head in ("{", "["):
        return "json"
    if head == "<":
        return "xml"
    return "csv"


def read(text: str, fmt: str) -> Table:
    if fmt == "json":
        records = _json_records(text)
    elif fmt == "csv":
        records = _csv_records(text)
    elif fmt == "xml":
        records = _xml_records(text)
    else:
        raise ValueError(f"unsupported format: {fmt}")
    truncated = len(records) > MAX_ROWS
    records = records[:MAX_ROWS]
    columns = list(dict.fromkeys(key for record in records for key in record))
    return Table(columns, records, truncated)


# json


def _json_records(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        if e.msg != "Extra data":
            raise
        # probably json lines, one object per line
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    return _records(data)


def _records(data) -> list[dict]:
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data):
            return [_flatten(x) for x in data]
        if data and all(isinstance(x, list) for x in data):
            return _rows_from_lists(data)
        return [{"value": _scalar(x)} for x in data]
    if isinstance(data, dict):
        # exports love wrapping the rows, like {"data": [...], "meta": {...}}
        nested = _largest_record_list(data)
        if nested is not None:
            return [_flatten(x) for x in nested]
        if data and all(isinstance(v, dict) for v in data.values()):
            return [{"key": k, **_flatten(v)} for k, v in data.items()]
        return [_flatten(data)]
    return [{"value": data}]


def _largest_record_list(obj: dict, depth: int = 0) -> list | None:
    best = None
    for value in obj.values():
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            found = value
        elif isinstance(value, dict) and depth < 3:
            found = _largest_record_list(value, depth + 1)
        else:
            continue
        if found is not None and (best is None or len(found) > len(best)):
            best = found
    return best


def _rows_from_lists(data: list[list]) -> list[dict]:
    first = data[0]
    if len(data) > 1 and all(isinstance(x, str) for x in first):
        header, body = first, data[1:]
    else:
        header, body = [f"col{i + 1}" for i in range(max(map(len, data)))], data
    return [dict(zip(header, map(_scalar, row))) for row in body]


def _flatten(obj: dict, prefix: str = "") -> dict:
    out = {}
    for key, value in obj.items():
        if isinstance(value, dict):
            out.update(_flatten(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = _scalar(value)
    return out


def _scalar(value):
    return json.dumps(value) if isinstance(value, (list, dict)) else value


# csv


def _csv_records(text: str) -> list[dict]:
    try:
        dialect = csv.Sniffer().sniff(text[:64 * 1024], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, None)
    if header is None:
        return []
    header = [h.strip() or f"col{i + 1}" for i, h in enumerate(header)]
    return [
        {h: (v.strip() or None) for h, v in zip(header, row)}
        for row in reader
        if any(v.strip() for v in row)
    ]


# xml


def _xml_records(text: str) -> list[dict]:
    root = ET.fromstring(text)
    parent, tag = _record_group(root)
    if parent is None:
        return [_xml_flatten(root)]
    return [_xml_flatten(el) for el in parent if el.tag == tag]


def _record_group(root: ET.Element):
    """the repeated element closest to the root is probably the rows"""
    level = [root]
    while level:
        best = None
        for el in level:
            if len(el):
                tag, n = Counter(child.tag for child in el).most_common(1)[0]
                if n >= 2 and (best is None or n > best[2]):
                    best = (el, tag, n)
        if best:
            return best[0], best[1]
        level = [child for el in level for child in el]
    return None, None


def _xml_flatten(el: ET.Element, prefix: str = "") -> dict:
    out = {f"{prefix}{_local(k)}": v for k, v in el.attrib.items()}
    if len(el) == 0:
        text = (el.text or "").strip()
        if text or not el.attrib:
            out[prefix.rstrip(".") or "value"] = text or None
        return out
    for child in el:
        out.update(_xml_flatten(child, f"{prefix}{_local(child.tag)}."))
    return out


def _local(tag: str) -> str:
    """drop the namespace from a tag or attribute name"""
    return tag.rsplit("}", 1)[-1]
