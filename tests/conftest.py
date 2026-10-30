import pytest

from fosset import llm


@pytest.fixture(autouse=True)
def no_real_llm_config(tmp_path, monkeypatch):
    # tests must never read your real config or cache, or they'd call the api for real
    monkeypatch.setattr(llm, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(llm, "CACHE_PATH", tmp_path / "cache" / "llm.json")
