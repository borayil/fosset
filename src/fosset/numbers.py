"""how numbers get written and read: the decimal mark and the thousands separator.

your mac's region decides by default, so in turkey it's 1.464 and 2,5, in the us 1,464 and 2.5.
the config or a flag can pick one instead. the same choice reads numbers that were written out
for people, like "21.985.979 ₺" or "%44"
"""

import math
import re
import sys
from functools import cache

from fosset import config

# (decimal mark, thousands separator)
ENGLISH = (".", ",")

_EXAMPLE = re.compile(r"^1(\D)234(\D)5$")
# a currency or percent sign in front or at the end, like %44, 44%, ₺1.464 or 21.985.979 TL
_UNIT = re.compile(r"^(?:[%₺$€£]|TL)\s*|\s*(?:[%₺$€£]|TL)$")


def to_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


@cache
def reader(separators: tuple[str, str]):
    """a to_number for numbers written out for people with these separators"""
    decimal, group = separators
    # a leading zero can't start a thousands group, so 0.875 never reads as 875
    shape = re.compile(rf"(?:\d+|[1-9]\d{{0,2}}(?:{re.escape(group)}\d{{3}})+)(?:{re.escape(decimal)}\d+)?")

    def parse(value) -> float | None:
        if not isinstance(value, str):
            return to_number(value)
        text = value.strip()
        if text.isascii() and text.isdigit():
            return float(text)  # plain whole numbers are most of it, skip the regex
        sign = ""
        if text[:1] in ("-", "+"):
            sign, text = text[0], text[1:]
        text = _UNIT.sub("", text)
        if not shape.fullmatch(text):
            return None
        return to_number(sign + text.replace(group, "").replace(decimal, "."))

    return parse


def readers(separators: tuple[str, str]) -> list:
    """the ways to read a column of numbers, most likely first. where the decimal mark is a
    comma, 1.464 means one thousand four hundred sixty four, so the local way goes first"""
    local = reader(separators)
    return [to_number, local] if separators[0] == "." else [local, to_number]


def parse_example(example: str) -> tuple[str, str]:
    """ "1.234,5" means a comma for decimals and a dot between thousands """
    match = _EXAMPLE.match(example.strip())
    if not match or match[1] == match[2]:
        raise ValueError(f'numbers should look like "1,234.5" or "1.234,5", not "{example}"')
    return match[2], match[1]


def example(separators: tuple[str, str]) -> str:
    decimal, group = separators
    return f"1{group}234{decimal}5"


def preferred(override: str | None = None) -> tuple[str, str]:
    """a flag wins, then the config, then the system"""
    if override:
        return parse_example(override)
    wanted = config.read().get("display", {}).get("numbers")
    if wanted:
        try:
            return parse_example(str(wanted))
        except ValueError as e:
            raise ValueError(f"{e}, fix [display] numbers in {config.CONFIG_PATH}") from e
    return system()


@cache
def system() -> tuple[str, str]:
    if sys.platform == "darwin":
        try:
            # macos keeps the number format with the region, not in the locale env vars.
            # foundation comes with the window anyway, so this costs nothing extra there
            from Foundation import NSLocale

            current = NSLocale.currentLocale()
            return str(current.decimalSeparator()), str(current.groupingSeparator())
        except ImportError:
            pass
    import locale

    try:
        previous = locale.setlocale(locale.LC_NUMERIC)
        locale.setlocale(locale.LC_NUMERIC, "")
        conventions = locale.localeconv()
        locale.setlocale(locale.LC_NUMERIC, previous)
    except locale.Error:
        return ENGLISH
    decimal = conventions["decimal_point"] or "."
    return decimal, conventions["thousands_sep"] or ("," if decimal == "." else ".")


def local(text: str, separators: tuple[str, str]) -> str:
    """turn a number python wrote, like 1,284.5, into the local way, like 1.284,5"""
    decimal, group = separators
    return text.translate({ord(","): group, ord("."): decimal})
