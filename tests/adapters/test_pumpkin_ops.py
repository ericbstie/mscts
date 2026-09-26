import uuid

import pytest

from mscts.adapters import vanilla
from mscts.adapters.base import PrepareError
from mscts.adapters.pumpkin import offline_uuid, ops_json


# What Pumpkin (nightly a4d6465) itself wrote to data/ops.json for console `op <name>`, offline.
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Notch", "ff4af744-2839-cc96-4605-0dd2214a30c1"),
        ("mscts_op", "dea1d220-d66e-fced-c40c-300338c9236f"),
    ],
)
def test_offline_uuid_is_the_one_pumpkin_gives_the_player(name: str, expected: str) -> None:
    assert offline_uuid(name) == uuid.UUID(expected)


def test_pumpkins_offline_uuid_is_not_vanillas() -> None:
    # Vanilla: MD5 of "OfflinePlayer:<name>", version 3. Pumpkin: the first 16 bytes of the
    # SHA-256 of the bare name. An ops.json entry with the vanilla UUID would op nobody.
    assert offline_uuid("Notch") != vanilla.offline_uuid("Notch")


def test_ops_json_lists_operators_exactly_as_pumpkin_writes_it() -> None:
    # Byte for byte what `op Notch` then `op mscts_op` wrote (serde_json, pretty, no newline
    # at the end). The key is bypasses_player_limit; vanilla's bypassesPlayerLimit would
    # fail to parse, and Pumpkin would then load no operators at all.
    assert ops_json(("Notch", "mscts_op")) == (
        "[\n"
        "  {\n"
        '    "uuid": "ff4af744-2839-cc96-4605-0dd2214a30c1",\n'
        '    "name": "Notch",\n'
        '    "level": 4,\n'
        '    "bypasses_player_limit": false\n'
        "  },\n"
        "  {\n"
        '    "uuid": "dea1d220-d66e-fced-c40c-300338c9236f",\n'
        '    "name": "mscts_op",\n'
        '    "level": 4,\n'
        '    "bypasses_player_limit": false\n'
        "  }\n"
        "]"
    )


def test_ops_json_is_empty_without_operators() -> None:
    assert ops_json(()) == "[]"


def test_an_operator_name_that_is_not_valid_unicode_is_refused() -> None:
    # Pumpkin would fail to parse the file and load no operators, logging it only.
    with pytest.raises(PrepareError, match=r"ServerSpec\.operators"):
        ops_json(("\ud800",))
