import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import anthropic
import pytest

from fosset import llm
from fosset.llm import Config, LLMError
from fosset.profile import Column
from fosset.recommend import Spec

COLUMNS = {
    "day": Column("day", "datetime", 10, 10, ["2026-10-01"]),
    "plan": Column("plan", "category", 10, 2, ["free", "pro"]),
    "mrr_eur": Column("mrr_eur", "number", 10, 10, ["12.5"]),
    "user_id": Column("user_id", "id", 10, 10, ["7"]),
}

ANSWER = {
    "charts": [
        {"kind": "line", "x": "day", "y": ["mrr_eur"], "color": "plan", "title": "MRR over time by plan"},
        {"kind": "bar", "x": "plan", "y": ["user_id"], "color": "", "title": "ids are not metrics"},
        {"kind": "line", "x": "nope", "y": [], "color": "", "title": "made up column"},
        {"kind": "kpi", "x": "", "y": ["mrr_eur"], "color": "", "title": "kpi needs one row"},
    ],
    "labels": [{"column": "mrr_eur", "label": "MRR (€)"}, {"column": "ghost", "label": "Ghost"}],
}


def write_config(text):
    llm.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    llm.CONFIG_PATH.write_text(text)


def test_no_config_means_no_llm():
    assert llm.load_config() is None
    write_config("# nothing here yet\n")
    assert llm.load_config() is None


def test_anthropic_config_defaults_to_opus():
    write_config('[llm]\nprovider = "anthropic"\n')
    assert llm.load_config() == Config("anthropic", "claude-opus-5-5")


def test_local_config():
    write_config('[llm]\nprovider = "local"\nmodel = "qwen3"\nurl = "http://localhost:11434/v1"\n')
    assert llm.load_config() == Config("local", "qwen3", None, "http://localhost:11434/v1")


@pytest.mark.parametrize(
    "text",
    ['[llm]\nprovider = "local"\nmodel = "qwen3"\n', '[llm]\nprovider = "openai"\n'],
)
def test_bad_config(text):
    write_config(text)
    with pytest.raises(ValueError):
        llm.load_config()


def test_to_specs_keeps_only_what_passes_the_constraint_check():
    specs, labels = llm.to_specs(ANSWER, COLUMNS, n_rows=10)
    assert specs == [Spec("line", "day", ("mrr_eur",), "plan", "MRR over time by plan")]
    assert labels == {"mrr_eur": "MRR (€)"}


def test_to_specs_survives_junk():
    assert llm.to_specs({"charts": [{"title": "no kind"}], "labels": [{}]}, COLUMNS, 10) == ([], {})


def test_fingerprint_follows_the_column_layout():
    config = Config("anthropic", "claude-opus-5-5")
    same = {**COLUMNS, "plan": Column("plan", "category", 99, 5, ["team"])}
    renamed_kind = {**COLUMNS, "plan": Column("plan", "text", 10, 2)}
    assert llm.fingerprint(COLUMNS, 10, config) == llm.fingerprint(same, 500, config)
    assert llm.fingerprint(COLUMNS, 10, config) != llm.fingerprint(renamed_kind, 10, config)
    assert llm.fingerprint(COLUMNS, 10, config) != llm.fingerprint(COLUMNS, 1, config)
    assert llm.fingerprint(COLUMNS, 10, config) != llm.fingerprint(COLUMNS, 10, Config("anthropic", "x"))


def test_cache_round_trip():
    assert llm.cached("k") is None
    llm.remember("k", ANSWER)
    llm.remember("other", {"charts": [], "labels": []})
    assert llm.cached("k") == ANSWER


def test_summary_never_includes_rows():
    summary = llm.summarize(COLUMNS, 10, "report.json")
    assert summary["rows"] == 10
    assert summary["columns"][0] == {"name": "day", "kind": "datetime", "distinct": 10, "samples": ["2026-10-01"]}


def test_worth_asking():
    assert llm.worth_asking(COLUMNS)
    assert not llm.worth_asking({"plan": COLUMNS["plan"], "user_id": COLUMNS["user_id"]})


# talking to anthropic, with a fake client so nothing goes over the network


class FakeAnthropic:
    def __init__(self, stop_reason="end_turn", **kwargs):
        self.init = kwargs
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
        FakeAnthropic.last = self

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=json.dumps(ANSWER))],
        )


def test_ask_anthropic(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    answer = llm.ask(Config("anthropic", "claude-opus-5-5", api_key="sk-test"), {"columns": []})
    assert answer == ANSWER
    request = FakeAnthropic.last.request
    assert FakeAnthropic.last.init["api_key"] == "sk-test"
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"]["format"]["schema"] == llm.SCHEMA
    assert request["output_config"]["effort"] == "low"
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]


def test_no_fallbacks_for_models_that_cant_use_them(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    llm.ask(Config("anthropic", "claude-haiku-5-5"), {"columns": []})
    assert "fallbacks" not in FakeAnthropic.last.request
    assert "betas" not in FakeAnthropic.last.request


def test_refusal_is_an_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: FakeAnthropic(stop_reason="refusal", **kw))
    with pytest.raises(LLMError, match="declined"):
        llm.ask(Config("anthropic", "claude-opus-5-5"), {"columns": []})


# talking to a local llm, with a tiny local server that speaks the openai chat api


@pytest.fixture
def local_llm():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, body, self.headers.get("Authorization")))
            out = json.dumps({"choices": [{"message": {"content": json.dumps(ANSWER)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1/", received
    server.shutdown()


def test_ask_local(local_llm):
    url, received = local_llm
    answer = llm.ask(Config("local", "qwen3", "secret", url), {"columns": []})
    assert answer == ANSWER
    path, body, auth = received[0]
    assert path == "/v1/chat/completions"
    assert body["model"] == "qwen3"
    assert body["response_format"]["json_schema"]["schema"] == llm.SCHEMA
    assert auth == "Bearer secret"


def test_local_llm_not_running():
    with pytest.raises(LLMError, match="couldn't reach"):
        llm.ask(Config("local", "qwen3", url="http://127.0.0.1:9/v1"), {"columns": []})
