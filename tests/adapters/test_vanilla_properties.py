import pytest

from mscts.adapters.vanilla import java_properties

# Captured from java.util.Properties.store(OutputStream, null) on Temurin 25.0.4.1
# (jshell, 2026-09-25): the JDK's own escaping is the source of truth.
JDK_VALUE_SAMPLES = [
    ("minecraft:flat", "minecraft\\:flat"),
    ("a=b", "a\\=b"),
    ("#x", "\\#x"),
    ("!x", "\\!x"),
    (" lead", "\\ lead"),
    ("  two", "\\  two"),
    ("trail ", "trail "),
    ("in ner", "in ner"),
    ("back\\slash", "back\\\\slash"),
    ("tab\there", "tab\\there"),
    ("new\nline", "new\\nline"),
    ("cr\rx", "cr\\rx"),
    ("ff\fx", "ff\\fx"),
    ("\x01ctl", "\\u0001ctl"),
    ("del\x7f", "del\\u007F"),
    ("\xe9", "\\u00E9"),
    ("\xa76gold", "\\u00A76gold"),
    ("\U0001f600", "\\uD83D\\uDE00"),
    ("{}", "{}"),
    ("", ""),
    ("~>^`|", "~>^`|"),
]

JDK_KEY_SAMPLES = [
    ("a b", "a\\ b"),
    ("a:b", "a\\:b"),
    ("query.port", "query.port"),
    (" lead", "\\ lead"),
]


@pytest.mark.parametrize(("value", "escaped"), JDK_VALUE_SAMPLES)
def test_values_are_escaped_like_the_jdk(value: str, escaped: str) -> None:
    assert java_properties({"k": value}).splitlines()[1] == f"k={escaped}"


@pytest.mark.parametrize(("key", "escaped"), JDK_KEY_SAMPLES)
def test_keys_are_escaped_like_the_jdk(key: str, escaped: str) -> None:
    assert java_properties({key: "v"}).splitlines()[1] == f"{escaped}=v"


def test_file_is_a_header_then_one_sorted_line_per_key() -> None:
    assert java_properties({"b": "2", "a-b": "3", "a": "1"}) == (
        "#Minecraft server properties\na=1\na-b=3\nb=2\n"
    )
