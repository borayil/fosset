import pytest

from fosset import config, llm, numbers


@pytest.fixture(autouse=True)
def no_real_llm_config(tmp_path, monkeypatch):
    # tests must never read your real config or cache, or they'd call the api for real
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(llm, "CACHE_PATH", tmp_path / "cache" / "llm.json")


@pytest.fixture(autouse=True)
def english_numbers(monkeypatch):
    # whatever region the machine running the tests is set to
    monkeypatch.setattr(numbers, "system", lambda: numbers.ENGLISH)
