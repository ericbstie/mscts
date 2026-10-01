import uuid
from pathlib import Path

import pytest

from mscts.adapters.base import Installation
from mscts.adapters.vanilla import VanillaAdapter, offline_uuid
from mscts.spec import ServerSpec
from mscts.target import TARGET

# Any host address of 127.0.0.0/8 will do: prepare only writes it into the config.
HOST = "127.1.2.3"

# prepare looks up a Java launcher; a fake Java 25 keeps the unit tier off the host's.
pytestmark = pytest.mark.usefixtures("java_25")


# From Java's UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(UTF_8)) in jshell.
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Notch", "b50ad385-829d-3141-a216-7e7d7539ba7f"),
        ("Steve", "5627dd98-e6be-3c21-b8a8-e92344183641"),
        ("mscts_op", "55c8fff7-78ee-3974-a185-69a798f915d3"),
        ("control", "cbe0d25b-d76c-3f34-a7fb-9022b56a0950"),
    ],
)
def test_offline_uuid_matches_java(name: str, expected: str) -> None:
    assert offline_uuid(name) == uuid.UUID(expected)


def ops_json(tmp_path: Path, spec: ServerSpec) -> str:
    installation = Installation(adapter="vanilla", target=TARGET, root=tmp_path / "cache")
    VanillaAdapter().prepare(installation, spec, tmp_path / "work")
    return (tmp_path / "work/ops.json").read_text(encoding="utf-8")


CONTROL_ENTRY = (
    "  {\n"
    '    "uuid": "cbe0d25b-d76c-3f34-a7fb-9022b56a0950",\n'
    '    "name": "control",\n'
    '    "level": 4,\n'
    '    "bypassesPlayerLimit": false\n'
    "  }"
)
"""Control's Bot, an operator on every Instance (level 4: every command)."""


def test_ops_json_lists_operators_exactly_as_vanilla_formats_it(tmp_path: Path) -> None:
    # Vanilla's own format (Gson, 2-space indent, no trailing newline), as written by `op`.
    assert ops_json(tmp_path, ServerSpec(host=HOST, port=25599, operators=("Notch", "Steve"))) == (
        "[\n" + CONTROL_ENTRY + ",\n"
        "  {\n"
        '    "uuid": "b50ad385-829d-3141-a216-7e7d7539ba7f",\n'
        '    "name": "Notch",\n'
        '    "level": 4,\n'
        '    "bypassesPlayerLimit": false\n'
        "  },\n"
        "  {\n"
        '    "uuid": "5627dd98-e6be-3c21-b8a8-e92344183641",\n'
        '    "name": "Steve",\n'
        '    "level": 4,\n'
        '    "bypassesPlayerLimit": false\n'
        "  }\n"
        "]"
    )


def test_control_is_the_only_operator_without_others(tmp_path: Path) -> None:
    assert ops_json(tmp_path, ServerSpec(host=HOST, port=25599)) == "[\n" + CONTROL_ENTRY + "\n]"


def test_control_is_listed_once_when_the_spec_names_it_too(tmp_path: Path) -> None:
    spec = ServerSpec(host=HOST, port=25599, operators=("control",))
    assert ops_json(tmp_path, spec) == "[\n" + CONTROL_ENTRY + "\n]"
