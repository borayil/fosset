"""the llm step. it only ever sees column names, kinds and a few sample values, never
the rows. it picks charts and writes titles, and answers get cached per column layout
so the same report never costs a second call"""

import hashlib
import json
import os
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from fosset.profile import Column
from fosset.recommend import Spec, merge, validate

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "fosset" / "config.toml"
CACHE_PATH = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "fosset" / "llm.json"
DEFAULT_MODEL = "claude-opus-5-5"
TIMEOUT = 30
# bump this when the prompt changes so old cached answers get ignored
PROMPT_VERSION = 1
# these models can hand a declined request to another model on anthropic's side
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

SYSTEM = """You pick charts for a data viewer. You get a summary of a table: its columns with their kind, \
how many distinct values they have and a few samples. You never see the rows.

Work out what the data is about, then return the charts that show it best, best first, at most 6. Each chart \
uses these kinds of columns:
line: x is a datetime or number column, y holds one number column, or nothing to count rows. color is an \
optional category column that splits the line into series.
bar: x is a category column, y holds one number column, or nothing to count rows.
scatter: x and y are both number columns.
hist: x is a number column.
kpi: y holds 1 to 12 number columns. Only when the table has exactly one row.

Only use column names exactly as given, with the kind the summary lists. Never use id, text or empty columns. \
Use an empty string for x or color when a chart has none. Prefer the metrics someone would actually care about \
and skip charts that would say nothing.

Titles are short and plain in sentence case, like "Orders over time by status" or "Revenue by plan". Don't put \
a time unit like daily or weekly in titles, the viewer picks that. Also give a short human label for every \
column you use, with the unit when it is obvious from the name, like "MRR (€)" for mrr_eur."""

SCHEMA = {
    "type": "object",
    "properties": {
        "charts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["line", "bar", "scatter", "hist", "kpi"]},
                    "x": {"type": "string"},
                    "y": {"type": "array", "items": {"type": "string"}},
                    "color": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["kind", "x", "y", "color", "title"],
                "additionalProperties": False,
            },
        },
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"column": {"type": "string"}, "label": {"type": "string"}},
                "required": ["column", "label"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["charts", "labels"],
    "additionalProperties": False,
}


class LLMError(Exception):
    pass


@dataclass
class Config:
    provider: str  # anthropic | local
    model: str
    api_key: str | None = None
    url: str | None = None


def load_config(path: Path | None = None) -> Config | None:
    """no config file, or no [llm] section, means no llm. fosset just uses its rules then"""
    path = path or CONFIG_PATH
    if not path.exists():
        return None
    llm = tomllib.loads(path.read_text()).get("llm")
    if not llm:
        return None
    provider = llm.get("provider", "anthropic")
    if provider == "anthropic":
        return Config(provider, llm.get("model", DEFAULT_MODEL), llm.get("api_key"))
    if provider == "local":
        if not llm.get("url") or not llm.get("model"):
            raise ValueError("a local llm needs both url and model in the config")
        return Config(provider, llm["model"], llm.get("api_key"), llm["url"])
    raise ValueError(f'provider should be "anthropic" or "local", not "{provider}"')


def worth_asking(columns: dict[str, Column]) -> bool:
    """with less than two usable columns there's nothing to decide"""
    return sum(c.kind in ("number", "datetime", "category") for c in columns.values()) >= 2


def summarize(columns: dict[str, Column], n_rows: int, name: str) -> dict:
    return {
        "file": name,
        "rows": n_rows,
        "columns": [
            {"name": c.name, "kind": c.kind, "distinct": c.distinct, "samples": c.samples}
            for c in columns.values()
        ],
    }


def fingerprint(columns: dict[str, Column], n_rows: int, config: Config) -> str:
    layout = [[c.name, c.kind] for c in columns.values()]
    raw = json.dumps([PROMPT_VERSION, config.provider, config.model, n_rows == 1, layout])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cached(key: str) -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text()).get(key)
    except (OSError, ValueError):
        return None


def remember(key: str, answer: dict) -> None:
    try:
        cache = json.loads(CACHE_PATH.read_text())
    except (OSError, ValueError):
        cache = {}
    cache[key] = answer
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(CACHE_PATH)


def ask(config: Config, summary: dict) -> dict:
    text = _ask_anthropic(config, summary) if config.provider == "anthropic" else _ask_local(config, summary)
    try:
        return json.loads(text)
    except ValueError as e:
        raise LLMError("the llm didn't send back valid json") from e


def to_specs(answer: dict, columns: dict[str, Column], n_rows: int) -> tuple[list[Spec], dict[str, str]]:
    """turn the answer into specs, dropping anything that fails the constraint check"""
    specs = []
    for chart in answer.get("charts", []):
        spec = Spec(
            chart.get("kind", ""),
            chart.get("x") or None,
            tuple(chart.get("y") or ()),
            chart.get("color") or None,
            chart.get("title", ""),
        )
        if validate(spec, columns, n_rows):
            specs.append(spec)
    labels = {
        item["column"]: item["label"]
        for item in answer.get("labels", [])
        if item.get("column") in columns and item.get("label")
    }
    return specs, labels


def apply_answer(answer: dict, columns: dict[str, Column], n_rows: int, rules: list[Spec]) -> list[Spec]:
    """put the answer's picks first, rule picks after, and hand its labels to the columns"""
    specs, labels = to_specs(answer, columns, n_rows)
    for name, label in labels.items():
        columns[name].label = label
    return merge(specs, rules)


def _ask_anthropic(config: Config, summary: dict) -> str:
    import anthropic  # takes a moment to import, so only when the llm is actually on

    client = anthropic.Anthropic(api_key=config.api_key, timeout=TIMEOUT, max_retries=1)
    extra = {}
    if config.model in FALLBACK_MODELS:
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        response = client.beta.messages.create(
            model=config.model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(summary)}],
            # picking charts is a quick job and the user is waiting, so keep the thinking short
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            **extra,
        )
    except anthropic.AuthenticationError as e:
        raise LLMError("the api key didn't work") from e
    except anthropic.RateLimitError as e:
        raise LLMError("rate limited by the api") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"the api said {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("couldn't reach the api") from e
    except anthropic.AnthropicError as e:
        raise LLMError(str(e)) from e

    if response.stop_reason == "refusal":
        raise LLMError("the model declined")
    if response.stop_reason == "max_tokens":
        raise LLMError("the answer got cut off")
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise LLMError("the answer had no text in it")
    return text


def _ask_local(config: Config, summary: dict) -> str:
    """anything that speaks the openai chat api works here: ollama, lm studio, mlx, llama.cpp"""
    body = {
        "model": config.model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(summary)}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "charts", "schema": SCHEMA}},
    }
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    request = urllib.request.Request(
        config.url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())["choices"][0]["message"]["content"]
    except OSError as e:
        raise LLMError(f"couldn't reach the local llm at {config.url}") from e
    except (ValueError, KeyError, IndexError) as e:
        raise LLMError("the local llm sent back something weird") from e
