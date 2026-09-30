"""Play-state schemas, one module per mechanic.

Every submodule maps packet names to schemas in `SERVERBOUND` and/or `CLIENTBOUND`, and records
the minecraft.wiki revision its field layouts were taken from. `SERVERBOUND` and `CLIENTBOUND`
here are those mappings merged in submodule name order, so a new mechanic adds a module and
never edits this file. Two submodules defining the same packet in the same direction is a
`SchemaError` at import, and so is a submodule defining neither mapping.
"""

import importlib
import pkgutil
from collections.abc import Iterable, Mapping
from types import ModuleType

from mscts.codec.schema import Schema, SchemaError


def _merge(modules: tuple[tuple[str, ModuleType], ...], attribute: str) -> Mapping[str, Schema]:
    merged: dict[str, Schema] = {}
    owners: dict[str, str] = {}
    for module_name, module in modules:
        for packet, schema in getattr(module, attribute, {}).items():
            if packet in owners:
                msg = f"{packet} is in {attribute} of both {owners[packet]} and {module_name}"
                raise SchemaError(msg)
            owners[packet] = module_name
            merged[packet] = schema
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

    Raises:
        SchemaError: Two modules define the same packet name in the same direction, or a
            module defines neither mapping (a misspelt name would be silently ignored).
    """
    loaded = tuple(modules)
    for module_name, module in loaded:
        if not (hasattr(module, "SERVERBOUND") or hasattr(module, "CLIENTBOUND")):
            msg = f"{module_name} defines neither SERVERBOUND nor CLIENTBOUND"
            raise SchemaError(msg)
    return _merge(loaded, "SERVERBOUND"), _merge(loaded, "CLIENTBOUND")


def _submodules() -> Iterable[tuple[str, ModuleType]]:
    names = sorted(info.name for info in pkgutil.iter_modules(__path__))
    return [(name, importlib.import_module(f"{__name__}.{name}")) for name in names]


SERVERBOUND, CLIENTBOUND = merge_submodules(_submodules())
