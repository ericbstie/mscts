"""Configuration schemas of Target 26.3, round-tripped through hand-built bytes."""

from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND


def string(text: str) -> bytes:
    """A String on the wire (every one here is shorter than 128 bytes)."""
    return bytes([len(text.encode())]) + text.encode()


def round_trip(direction: Direction, name: str, fields: Mapping[str, object], data: bytes) -> None:
    assert CODEC.packet_id(State.CONFIGURATION, direction, name) == data[0]
    assert CODEC.encode(State.CONFIGURATION, direction, name, fields) == data
    packet = CODEC.decode(State.CONFIGURATION, direction, data)
    assert (packet.name, packet.fields) == (name, fields)


def test_custom_payload_is_a_channel_and_the_rest_of_the_packet() -> None:
    brand = string("vanilla")  # minecraft:brand carries a String
    data = bytes([0x01]) + string("minecraft:brand") + brand
    fields = {"channel": "minecraft:brand", "data": brand}
    round_trip(CLIENTBOUND, "minecraft:custom_payload", fields, data)


def test_the_client_sends_its_brand_in_a_plugin_message() -> None:
    # Plugin Message (serverbound), wiki revision 3790659: Channel Identifier, then Data,
    # the rest of the packet. minecraft:brand's data is a String.
    brand = string("vanilla")
    data = bytes([0x02]) + string("minecraft:brand") + brand
    fields = {"channel": "minecraft:brand", "data": brand}
    round_trip(SERVERBOUND, "minecraft:custom_payload", fields, data)


CLIENT_INFORMATION = {
    "locale": "en_us",
    "view_distance": 12,
    "chat_mode": 0,
    "chat_colors": True,
    "displayed_skin_parts": 0x7F,
    "main_hand": 1,
    "enable_text_filtering": False,
    "allow_server_listings": True,
    "particle_status": 0,
}


def test_client_information_is_the_wiki_layout() -> None:
    # Client Information (configuration), wiki revision 3790659: Locale String (16), View
    # Distance Byte, Chat Mode VarInt Enum, Chat Colors Boolean, Displayed Skin Parts
    # Unsigned Byte, Main Hand VarInt Enum, Enable text filtering Boolean, Allow server
    # listings Boolean, Particle Status VarInt Enum.
    data = bytes([0x00]) + string("en_us") + bytes.fromhex("0c 00 01 7f 01 00 01 00")
    round_trip(SERVERBOUND, "minecraft:client_information", CLIENT_INFORMATION, data)


def test_displayed_skin_parts_is_an_unsigned_byte() -> None:
    data = bytes([0x00]) + string("en_us") + bytes.fromhex("0c 00 01 ff 01 00 01 00")
    packet = CODEC.decode(State.CONFIGURATION, SERVERBOUND, data)
    assert (packet.fields or {}).get("displayed_skin_parts") == 0xFF
    for parts in (-1, 0x100):
        fields = {**CLIENT_INFORMATION, "displayed_skin_parts": parts}
        with pytest.raises(CodecError, match="displayed_skin_parts: "):
            CODEC.encode(State.CONFIGURATION, SERVERBOUND, "minecraft:client_information", fields)


def test_the_locale_is_at_most_16_characters() -> None:
    # ClientInformation reads the language with readUtf(16) (26.3 javap).
    fields = {**CLIENT_INFORMATION, "locale": "x" * 17}
    with pytest.raises(CodecError, match="locale: "):
        CODEC.encode(State.CONFIGURATION, SERVERBOUND, "minecraft:client_information", fields)


def test_update_enabled_features_is_a_list_of_identifiers() -> None:
    data = bytes([0x0D, 0x01]) + string("minecraft:vanilla")
    fields = {"feature_flags": ["minecraft:vanilla"]}
    round_trip(CLIENTBOUND, "minecraft:update_enabled_features", fields, data)


KNOWN_PACKS = {"known_packs": [{"namespace": "minecraft", "id": "core", "version": "26.3"}]}
KNOWN_PACKS_BODY = bytes([0x01]) + string("minecraft") + string("core") + string("26.3")


@pytest.mark.parametrize(("direction", "packet_id"), [(CLIENTBOUND, 0x0F), (SERVERBOUND, 0x07)])
def test_select_known_packs_is_the_same_list_both_ways(
    direction: Direction, packet_id: int
) -> None:
    data = bytes([packet_id]) + KNOWN_PACKS_BODY
    round_trip(direction, "minecraft:select_known_packs", KNOWN_PACKS, data)


def test_the_client_offers_at_most_64_known_packs() -> None:
    # ServerboundSelectKnownPacks reads `ByteBufCodecs.list(64)` (26.3, javap).
    packs = {"known_packs": [{"namespace": "a", "id": "b", "version": "c"}] * 65}
    with pytest.raises(CodecError, match="known_packs: array length 65 exceeds max 64"):
        CODEC.encode(State.CONFIGURATION, SERVERBOUND, "minecraft:select_known_packs", packs)


def test_registry_data_entries_carry_optional_nbt() -> None:
    nbt = bytes.fromhex("0a 01 0001 62 01 00")  # a compound {b: 1b}
    data = (
        bytes([0x07])
        + string("minecraft:dimension_type")
        + bytes([0x02])
        + string("minecraft:overworld")
        + bytes([0x00])  # no data: sourced from the known pack
        + string("minecraft:the_end")
        + bytes([0x01])
        + nbt
    )
    fields = {
        "registry_id": "minecraft:dimension_type",
        "entries": [
            {"entry_id": "minecraft:overworld", "data": None},
            {"entry_id": "minecraft:the_end", "data": nbt},
        ],
    }
    round_trip(CLIENTBOUND, "minecraft:registry_data", fields, data)


def test_update_tags_is_registries_of_tags_of_ids() -> None:
    data = (
        bytes([0x0E, 0x01])
        + string("minecraft:block")
        + bytes([0x01])
        + string("minecraft:climbable")
        + bytes.fromhex("02 05 ac02")  # entries 5 and 300
    )
    fields = {
        "tagged_registries": [
            {
                "registry": "minecraft:block",
                "tags": [{"tag_name": "minecraft:climbable", "entries": [5, 300]}],
            }
        ]
    }
    round_trip(CLIENTBOUND, "minecraft:update_tags", fields, data)


@pytest.mark.parametrize(
    ("direction", "name", "packet_id"),
    [
        (CLIENTBOUND, "minecraft:finish_configuration", 0x03),
        (SERVERBOUND, "minecraft:finish_configuration", 0x03),
        (SERVERBOUND, "minecraft:accept_code_of_conduct", 0x09),
    ],
)
def test_packets_without_fields(direction: Direction, name: str, packet_id: int) -> None:
    round_trip(direction, name, {}, bytes([packet_id]))


@pytest.mark.parametrize(("direction", "packet_id"), [(CLIENTBOUND, 0x04), (SERVERBOUND, 0x04)])
def test_keep_alive_is_a_long_both_ways(direction: Direction, packet_id: int) -> None:
    data = bytes([packet_id]) + (-2).to_bytes(8, "big", signed=True)
    round_trip(direction, "minecraft:keep_alive", {"keep_alive_id": -2}, data)


def test_code_of_conduct_is_a_string() -> None:
    data = bytes([0x14]) + string("Be kind.")
    round_trip(CLIENTBOUND, "minecraft:code_of_conduct", {"code_of_conduct": "Be kind."}, data)


def test_disconnect_is_an_nbt_text_component() -> None:
    reason = bytes.fromhex("08 0003") + b"bye"  # a plain text component: a String tag
    round_trip(CLIENTBOUND, "minecraft:disconnect", {"reason": reason}, bytes([0x02]) + reason)
