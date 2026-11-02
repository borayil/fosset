import pytest

from fosset import config, numbers
from fosset.numbers import ENGLISH, local, parse_example, preferred, reader, readers, to_number

TURKISH = (",", ".")
REAL_SYSTEM = numbers.system  # grabbed before the fixture in conftest swaps it out


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.464", 1464.0),
        ("21.985.979 ₺", 21985979.0),
        ("₺21.985.979", 21985979.0),
        ("1.234,5 TL", 1234.5),
        ("%44", 44.0),
        ("-%5,5", -5.5),
        ("820", 820.0),
        ("2,25", 2.25),
        (12.5, 12.5),  # real numbers stay what they are
        ("0.875", None),  # a leading zero can't start a thousands group
        ("12.5", None),
        ("1.2.3", None),
        ("abc", None),
        ("", None),
        ("%", None),
    ],
)
def test_turkish_reader(value, expected):
    assert reader(TURKISH)(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1,464", 1464.0), ("$1,234.50", 1234.5), ("44%", 44.0), ("0.875", 0.875), ("1.464", 1.464), ("1,5", None)],
)
def test_english_reader(value, expected):
    assert reader(ENGLISH)(value) == expected


def test_the_local_way_goes_first_where_the_decimal_mark_is_a_comma():
    assert readers(ENGLISH) == [to_number, reader(ENGLISH)]
    assert readers(TURKISH) == [reader(TURKISH), to_number]


@pytest.mark.parametrize(
    ("example", "expected"),
    [("1.234,5", (",", ".")), ("1,234.5", (".", ",")), ("1 234,5", (",", " ")), (" 1'234.5 ", (".", "'"))],
)
def test_parse_example(example, expected):
    assert parse_example(example) == expected


@pytest.mark.parametrize("example", ["1234.5", "1.234.5", "tr", ""])
def test_bad_examples(example):
    with pytest.raises(ValueError, match="should look like"):
        parse_example(example)


def test_flag_beats_config_beats_system(monkeypatch):
    monkeypatch.setattr(numbers, "system", lambda: ("x", "y"))
    assert preferred() == ("x", "y")
    config.CONFIG_PATH.write_text('[display]\nnumbers = "1.234,5"\n')
    assert preferred() == TURKISH
    assert preferred("1,234.5") == ENGLISH


def test_bad_config_says_where_to_fix_it():
    config.CONFIG_PATH.write_text('[display]\nnumbers = "turkish"\n')
    with pytest.raises(ValueError, match=r"fix \[display\] numbers in .*config.toml"):
        preferred()


def test_broken_toml_says_which_file():
    config.CONFIG_PATH.write_text("[display\n")
    with pytest.raises(ValueError, match="isn't valid toml"):
        preferred()


def test_local():
    assert local("1,284.5", TURKISH) == "1.284,5"
    assert local("12.9K", TURKISH) == "12,9K"
    assert local("1,284.5", ENGLISH) == "1,284.5"


def test_the_real_system_gives_two_different_separators():
    decimal, group = REAL_SYSTEM()
    assert decimal and group and decimal != group
