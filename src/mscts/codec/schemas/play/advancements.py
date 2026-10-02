"""Play-state schemas for advancements: what a player is shown in `update_advancements`.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659 (2026-09-23,
"26.3, protocol 777"), "Update Advancements", raw wikitext. Checked against the 26.3 client jar
with `javap`, which wins where the wiki is older (#106):

- `ClientboundUpdateAdvancementsPacket.STREAM_CODEC`: a Boolean (reset), a list of
  `PositionedAdvancement`, the removed ids (`Identifier.STREAM_CODEC` read into a
  `LinkedHashSet`), the progress (`ByteBufCodecs.map(HashMap::new, Identifier.STREAM_CODEC,
  AdvancementProgress.STREAM_CODEC)`), then a Boolean (show advancements).
- `PositionedAdvancement` is an `AdvancementHolder` (an Identifier, then the `Advancement`),
  then its x and y as Floats. Unlike the wiki, x and y follow the advancement, whether or not
  it has a display, and are not in the display.
- `Advancement.STREAM_CODEC`: an optional parent Identifier, an optional `DisplayInfo`, the
  requirements (a list of lists of `ByteBufCodecs.STRING_UTF8`, at most 32767), and a Boolean
  (sends telemetry).
- `DisplayInfo.serializeToNetwork`: the title and the description (text components), the icon
  (an `ItemStackTemplate`, not a Slot as the wiki says), the frame (`AdvancementType`,
  `ByteBufCodecs.idMapper`: task 0, challenge 1, goal 2), an Int of flags (0x01 a background,
  0x02 show a toast, 0x04 hidden), and the background's Identifier only if flags & 0x01.
- `AdvancementProgress.STREAM_CODEC`: `ByteBufCodecs.map(HashMap::new, STRING_UTF8,
  CriterionProgress.STREAM_CODEC)`, and a criterion's progress is an optional
  `ByteBufCodecs.INSTANT`, a Long of epoch milliseconds: when it was obtained.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from mscts.codec.components import ITEM_STACK_TEMPLATE
from mscts.codec.schema import (
    BOOL,
    FLOAT,
    IDENTIFIER,
    INT,
    LONG,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    String,
)
from mscts.codec.shapes import ENUM, TEXT_COMPONENT
from mscts.codec.wire import Reader, WireError, Writer

_HAS_BACKGROUND = 0x01
"""The display flag that a background texture follows; show a toast (0x02) and hidden (0x04)
carry no data."""

_DISPLAY_HEAD = Schema(
    title=TEXT_COMPONENT,
    description=TEXT_COMPONENT,
    icon=ITEM_STACK_TEMPLATE,
    frame_type=ENUM,
    flags=INT,
)
"""A display's fields before its background texture."""


@dataclass(frozen=True, slots=True)
class _Display:
    """An advancement's display: `_DISPLAY_HEAD`, then `background_texture` if flags & 0x01.

    Its value has `background_texture` None when the flags announce none. Writing refuses a
    display whose background texture disagrees with its flags.
    """

    def read(self, reader: Reader) -> dict[str, object]:
        display = _DISPLAY_HEAD.read(reader)
        announced = cast("int", display["flags"]) & _HAS_BACKGROUND
        try:
            display["background_texture"] = IDENTIFIER.read(reader) if announced else None
        except WireError as exc:
            msg = f"background_texture: {exc}"
            raise WireError(msg) from exc
        return display

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, Mapping):
            msg = f"expected a mapping of field names to values, got {type(value).__name__}"
            raise WireError(msg)
        head = dict(cast("Mapping[str, object]", value).items())
        if "background_texture" not in head:
            msg = "missing field(s) background_texture"
            raise WireError(msg)
        background = head.pop("background_texture")
        _DISPLAY_HEAD.write(writer, head)
        flags = cast("int", head["flags"])
        if (background is not None) != bool(flags & _HAS_BACKGROUND):
            msg = (
                f"background_texture: present only if flags & {_HAS_BACKGROUND} (flags are {flags})"
            )
            raise WireError(msg)
        if background is not None:
            IDENTIFIER.write(writer, background)


_CRITERION = String(32767)

CLIENTBOUND: Mapping[str, Schema] = {
    # Update Advancements: whether to clear what the client has; the advancements to add, each
    # an id, its parent's, its display, its requirements (each a list of criteria, any of which
    # meets it) and where it sits in its tab; the ids to remove; each advancement's progress,
    # by criterion, with when it was obtained; whether to show the advancements.
    "minecraft:update_advancements": Schema(
        reset=BOOL,
        advancements=PrefixedArray(
            Schema(
                id=IDENTIFIER,
                parent_id=PrefixedOptional(IDENTIFIER),
                display=PrefixedOptional(_Display()),
                requirements=PrefixedArray(PrefixedArray(_CRITERION)),
                sends_telemetry_data=BOOL,
                x=FLOAT,
                y=FLOAT,
            )
        ),
        removed=PrefixedArray(IDENTIFIER),
        progress=PrefixedArray(
            Schema(
                id=IDENTIFIER,
                criteria=PrefixedArray(
                    Schema(criterion=_CRITERION, obtained=PrefixedOptional(LONG))
                ),
            )
        ),
        show_advancements=BOOL,
    ),
}
