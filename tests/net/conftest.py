import asyncio
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, Direction, State
from mscts.codec.schema import LONG, Schema, String
from mscts.net import Connection
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
    return Transcript(group_id="net/test", server="fake")


@pytest.fixture
def stream_writers(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.StreamWriter]:
    """The StreamWriter of every Connection made in the test."""
    writers: list[asyncio.StreamWriter] = []
    init = Connection.__init__

    def recording_init(  # noqa: PLR0913 - Connection.__init__, as it is
        connection: Connection,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        codec: Codec,
        *,
        bot: str,
        transcript: Transcript,
    ) -> None:
        writers.append(writer)
        init(connection, reader, writer, codec, bot=bot, transcript=transcript)

    monkeypatch.setattr(Connection, "__init__", recording_init)
    return writers
