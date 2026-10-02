"""`update_advancements`: the advancements a player is shown, and their progress.

The recorded payloads are what two fresh vanilla 26.3 Instances sent at a join (#30, worker
AR's join probe): the same two recipe advancements, but for when a criterion was obtained.
"""

from pathlib import Path

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, Packet, State
from mscts.codec.wire import Writer

CODEC = Codec.load("26.3")
CLIENTBOUND = Direction.CLIENTBOUND
NAME = "minecraft:update_advancements"
DATA = Path(__file__).parent / "data"

CRAFTING_TABLE = "minecraft:recipes/decorations/crafting_table"
ROOT = "minecraft:recipes/root"


def _framed(payload: bytes) -> bytes:
    """`payload` behind the packet's id."""
    return Writer().var_int(CODEC.packet_id(State.PLAY, CLIENTBOUND, NAME)).to_bytes() + payload


def recorded(boot: int) -> Packet:
    payload = (DATA / f"vanilla-26.3-boot{boot}-update_advancements.bin").read_bytes()
    return CODEC.decode(State.PLAY, CLIENTBOUND, _framed(payload))


def _join(obtained: int) -> dict[str, object]:
    """What vanilla sends a player joining a new world: the crafting table's recipe unlocked."""
    return {
        "reset": True,
        "advancements": [
            {
                "id": CRAFTING_TABLE,
                "parent_id": ROOT,
                "display": None,
                "requirements": [["has_the_recipe", "unlock_right_away"]],
                "sends_telemetry_data": False,
                "x": 0.0,
                "y": 0.0,
            },
            {
                "id": ROOT,
                "parent_id": None,
                "display": None,
                "requirements": [["impossible"]],
                "sends_telemetry_data": False,
                "x": 0.0,
                "y": 0.0,
            },
        ],
        "removed": [],
        "progress": [
            {
                "id": CRAFTING_TABLE,
                "criteria": [
                    {"criterion": "has_the_recipe", "obtained": None},
                    {"criterion": "unlock_right_away", "obtained": obtained},
                ],
            },
            {"id": ROOT, "criteria": [{"criterion": "impossible", "obtained": None}]},
        ],
        "show_advancements": True,
    }


@pytest.mark.parametrize(("boot", "obtained"), [(1, 1790944982000), (2, 1790944986000)])
def test_a_recorded_join_decodes_and_encodes_byte_for_byte(boot: int, obtained: int) -> None:
    packet = recorded(boot)

    fields = packet.fields
    assert fields == _join(obtained)
    assert fields is not None
    assert CODEC.encode(State.PLAY, CLIENTBOUND, NAME, fields) == _framed(packet.payload)


TITLE, DESCRIPTION = b"\x08\x00\x01T", b"\x08\x00\x01D"  # network NBT: a string tag
ICON = {"item": 7, "count": 1, "components": {"added": [], "removed": []}}


def _shown(display: dict[str, object]) -> dict[str, object]:
    """One advancement with `display`, at (1, 2), with no requirement, progress or removal."""
    return {
        "reset": False,
        "advancements": [
            {
                "id": "minecraft:a",
                "parent_id": None,
                "display": display,
                "requirements": [],
                "sends_telemetry_data": True,
                "x": 1.0,
                "y": 2.0,
            }
        ],
        "removed": [],
        "progress": [],
        "show_advancements": False,
    }


def _display(flags: int, background: str | None) -> dict[str, object]:
    return {
        "title": TITLE,
        "description": DESCRIPTION,
        "icon": ICON,
        "frame_type": 2,
        "flags": flags,
        "background_texture": background,
    }


def _shown_payload(display: bytes) -> bytes:
    position = b"\x3f\x80\x00\x00\x40\x00\x00\x00"
    return b"\x00\x01\x0bminecraft:a\x00\x01" + display + b"\x00\x01" + position + b"\x00\x00\x00"


DISPLAY_HEAD = TITLE + DESCRIPTION + b"\x07\x01\x00\x00" + b"\x02"


@pytest.mark.parametrize(
    ("flags", "background", "data"),
    [
        (0x01 | 0x02, "minecraft:b", b"\x00\x00\x00\x03\x0bminecraft:b"),
        (0x02 | 0x04, None, b"\x00\x00\x00\x06"),
    ],
    ids=["with a background", "without"],
)
def test_a_display_has_a_background_texture_only_if_its_flags_say_so(
    flags: int, background: str | None, data: bytes
) -> None:
    fields = _shown(_display(flags, background))
    payload = _shown_payload(DISPLAY_HEAD + data)

    assert CODEC.encode(State.PLAY, CLIENTBOUND, NAME, fields) == _framed(payload)
    assert CODEC.decode(State.PLAY, CLIENTBOUND, _framed(payload)).fields == fields


@pytest.mark.parametrize(
    ("flags", "background"), [(0x01, None), (0x02, "minecraft:b")], ids=["missing", "unasked"]
)
def test_a_background_texture_its_flags_disagree_with_is_refused(
    flags: int, background: str | None
) -> None:
    with pytest.raises(CodecError, match="background_texture: present only if flags & 1"):
        CODEC.encode(State.PLAY, CLIENTBOUND, NAME, _shown(_display(flags, background)))


def test_a_display_must_name_its_background_texture() -> None:
    display = _display(0, None)
    del display["background_texture"]
    with pytest.raises(CodecError, match="missing field"):
        CODEC.encode(State.PLAY, CLIENTBOUND, NAME, _shown(display))


def test_removed_advancements_are_identifiers() -> None:
    fields = {**_shown(_display(0, None)), "advancements": [], "removed": ["minecraft:a"]}
    payload = b"\x00\x00\x01\x0bminecraft:a\x00\x00"

    assert CODEC.encode(State.PLAY, CLIENTBOUND, NAME, fields) == _framed(payload)
    assert CODEC.decode(State.PLAY, CLIENTBOUND, _framed(payload)).fields == fields
