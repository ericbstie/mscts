"""What the combat and player Group tests share about mobs."""

from mscts.codec.registry_names import registry_names
from mscts.target import TARGET

HUSK = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index("minecraft:husk")


NONE_LEFT = "commands.execute.conditional.fail"
