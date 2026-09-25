import dataclasses
from pathlib import Path

import pytest

from mscts.adapters.base import Installation, LaunchPlan
from mscts.net import Endpoint
from mscts.target import TARGET

INSTALLATION = Installation(adapter="vanilla", target=TARGET, root=Path("/cache/vanilla/26.3"))
PLAN = LaunchPlan(
    argv=("java", "-jar", "server.jar"),
    cwd=Path("/work"),
    env={"PATH": "/bin"},
    endpoint=Endpoint(host="127.0.0.1", port=25599),
    stop_stdin=b"stop\n",
)


def test_installation_holds_adapter_target_and_root() -> None:
    assert (INSTALLATION.adapter, INSTALLATION.target, INSTALLATION.root) == (
        "vanilla",
        TARGET,
        Path("/cache/vanilla/26.3"),
    )


def test_launch_plan_may_stop_by_signal() -> None:
    assert dataclasses.replace(PLAN, stop_stdin=None).stop_stdin is None


@pytest.mark.parametrize(
    ("value", "field"),
    [(value, field.name) for value in (INSTALLATION, PLAN) for field in dataclasses.fields(value)],
)
def test_is_frozen(value: Installation | LaunchPlan, field: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, getattr(value, field))


@pytest.mark.parametrize("value", [INSTALLATION, PLAN])
def test_has_slots(value: Installation | LaunchPlan) -> None:
    assert not hasattr(value, "__dict__")
