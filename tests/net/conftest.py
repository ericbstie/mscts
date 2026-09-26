from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, Direction, State
from mscts.codec.schema import LONG, Schema, String
from mscts.target import TARGET
from mscts.transcript import Transcript

_TOY_IDS: Mapping[tuple[State, Direction], Mapping[str, int]] = {
    (State.HANDSHAKE, Direction.SERVERBOUND): {"test:request": 0x00, "test:hello": 0x01},
    (State.HANDSHAKE, Direction.CLIENTBOUND): {"test:reply": 0x00, "test:empty": 0x01},
}
_TOY_SCHEMAS: Mapping[tuple[State, Direction], Mapping[str, Schema]] = {
    (State.HANDSHAKE, Direction.SERVERBOUND): {
        "test:request": Schema(value=LONG),
        "test:hello": Schema(name=String(16)),
    },
    (State.HANDSHAKE, Direction.CLIENTBOUND): {
        "test:reply": Schema(value=LONG),
        "test:empty": Schema(),
    },
}


@pytest.fixture(scope="session")
def codec() -> Codec:
    """The Target's Codec."""
    return Codec.for_target(TARGET)


@pytest.fixture(scope="session")
def toy_codec() -> Codec:
    """A handshake-state-only Codec, for transport tests that need no State changes.

    Serverbound: `test:request` (value: Long), `test:hello` (name: String(16)).
    Clientbound: `test:reply` (value: Long), `test:empty` (no fields).
    """
    return Codec(_TOY_IDS, _TOY_SCHEMAS)


@pytest.fixture
def transcript() -> Transcript:
    """A fresh Transcript."""
    return Transcript(scenario_id="net/test", server="fake")
