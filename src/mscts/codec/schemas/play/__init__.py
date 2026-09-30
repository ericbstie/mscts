"""Play-state schemas, one module per mechanic.

Every submodule maps packet names to schemas in `SERVERBOUND` and/or `CLIENTBOUND`, and records
the minecraft.wiki revision its field layouts were taken from. `SERVERBOUND` and `CLIENTBOUND`
here are those mappings merged in submodule name order, so a new mechanic adds a module and
never edits this file.
"""

import importlib
import pkgutil
from collections.abc import Iterable, Mapping
from types import ModuleType

from mscts.codec.schema import Schema


def _merge(modules: tuple[tuple[str, ModuleType], ...], attribute: str) -> Mapping[str, Schema]:
    merged: dict[str, Schema] = {}
    for _, module in modules:
        merged.update(getattr(module, attribute, {}))
    return merged


def merge_submodules(
    modules: Iterable[tuple[str, ModuleType]],
) -> tuple[Mapping[str, Schema], Mapping[str, Schema]]:
    """Merge the `SERVERBOUND` and `CLIENTBOUND` mappings of `modules`.

    Args:
        modules: Each submodule's name and module. A module may define only one of the two
            mappings.

    Returns:
        The merged serverbound mapping, then the merged clientbound mapping.
    """
    loaded = tuple(modules)
    return _merge(loaded, "SERVERBOUND"), _merge(loaded, "CLIENTBOUND")


def _submodules() -> Iterable[tuple[str, ModuleType]]:
    names = sorted(info.name for info in pkgutil.iter_modules(__path__))
    return [(name, importlib.import_module(f"{__name__}.{name}")) for name in names]


SERVERBOUND, CLIENTBOUND = merge_submodules(_submodules())
