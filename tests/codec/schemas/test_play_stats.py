"""The play schemas the barrier (`Bot.sync`) sends, round-tripped through hand-built bytes."""

from mscts.codec.packets import Codec, Direction, State
from mscts.codec.schemas.play.stats import REQUEST_STATS

CODEC = Codec.load("26.3")


def test_client_command_is_its_action_as_a_var_int() -> None:
    data = bytes([0x0C, 0x01])
    fields = {"action": REQUEST_STATS}

    assert CODEC.packet_id(State.PLAY, Direction.SERVERBOUND, "minecraft:client_command") == 0x0C
    assert (
        CODEC.encode(State.PLAY, Direction.SERVERBOUND, "minecraft:client_command", fields) == data
    )
    packet = CODEC.decode(State.PLAY, Direction.SERVERBOUND, data)
    assert (packet.name, packet.fields) == ("minecraft:client_command", fields)
