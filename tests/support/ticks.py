"""What a tick-exact Group's Bots sent around the steps of Control, read from its Transcript."""

from collections.abc import Set as AbstractSet

from mscts.codec.packets import Direction
from mscts.codec.schemas.play.stats import REQUEST_STATS
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.transcript import Event, Transcript
from support.control import CHAT_COMMAND, CLIENT_COMMAND, CONTROL


def barriers_before_steps(transcript: Transcript, bot: str, actions: AbstractSet[str]) -> list[int]:
    """For each of `bot`'s `actions` that a step follows in its window: its barrier's requests.

    That is, how many statistics requests `bot` sent after the action and before Control sent
    the window's next `tick step 1` (#360). An action no step follows in its window is left out.
    """
    sent = serverbound_events(transcript)
    windows, steps, requests = _windows(transcript), _steps_sent(sent), requests_sent(sent, bot)
    acts = [event.t_ns for event in sent if event.bot == bot and event.packet.name in actions]
    counts = []
    for acted in acts:
        step = _next_step_in_window(acted, windows, steps)
        if step is not None:
            counts.append(sum(acted < t < step for t in requests))
    return counts


def serverbound_events(transcript: Transcript) -> list[Event]:
    """Every serverbound event, in time order."""
    return [event for event in transcript.events if event.packet.direction is Direction.SERVERBOUND]


def _windows(transcript: Transcript) -> list[tuple[int, int]]:
    """When each Observation window opened and closed."""
    opened = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closed = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    return list(zip(opened, closed, strict=True))


def _steps_sent(sent: list[Event]) -> list[int]:
    """When Control sent each `tick step 1`."""
    return [
        event.t_ns
        for event in sent
        if event.bot == CONTROL
        and event.packet.name == CHAT_COMMAND
        and (event.packet.fields or {})["command"] == "tick step 1"
    ]


def requests_sent(sent: list[Event], bot: str) -> list[int]:
    """When `bot` sent each statistics request."""
    return [
        event.t_ns
        for event in sent
        if event.bot == bot
        and event.packet.name == CLIENT_COMMAND
        and (event.packet.fields or {})["action"] == REQUEST_STATS
    ]


def _next_step_in_window(t_ns: int, windows: list[tuple[int, int]], steps: list[int]) -> int | None:
    """The first step after `t_ns` in the window that holds it, if any."""
    closed = next((closed for opened, closed in windows if opened <= t_ns <= closed), None)
    if closed is None:
        return None
    return next((t for t in steps if t_ns < t <= closed), None)
