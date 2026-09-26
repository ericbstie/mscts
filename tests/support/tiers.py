"""What each live tier needs installed, and whether it is (ADR-0008: tests never install)."""

from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet
from pathlib import Path
from types import MappingProxyType

from mscts import install
from mscts.adapters.base import Adapter, ProvisionError
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.adapters.vanilla import VanillaAdapter
from mscts.target import TARGET

# The Adapter whose Installation each live tier's marker needs.
NEEDS: Mapping[str, Callable[[], Adapter]] = MappingProxyType(
    {"reference": VanillaAdapter, "candidate": PumpkinAdapter}
)


def missing_installations(markers: AbstractSet[str], cache_dir: Path) -> list[str]:
    """Why each Installation the tiers in `markers` need is unusable, naming its fix."""
    problems: list[str] = []
    for marker, adapter in NEEDS.items():
        if marker in markers:
            try:
                install.require(adapter(), TARGET, cache_dir)
            except ProvisionError as error:
                problems.append(str(error))
    return problems
