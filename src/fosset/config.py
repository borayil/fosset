"""~/.config/fosset/config.toml, where the llm settings and the display preferences live"""

import os
import tomllib
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "fosset" / "config.toml"


def read() -> dict:
    """no file means no preferences, everything falls back to the defaults"""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return tomllib.loads(CONFIG_PATH.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{CONFIG_PATH} isn't valid toml, {e}") from e
