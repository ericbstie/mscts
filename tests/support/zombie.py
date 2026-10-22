"""The zombie the live entity tests summon, and the command that kills it again."""

TAG = "mscts_entities"
"""The tag on what this test summons, so the cleanup kills only that."""


ZOMBIE_AT = (2.5, -60.0, 0.5)
"""On the flat world's grass, two blocks east of the watcher."""


SUMMON = (
    "summon minecraft:zombie 2.5 -60 0.5 {NoAI:1b,PersistenceRequired:1b,"
    f'Tags:["{TAG}"],equipment:{{head:{{id:"minecraft:leather_helmet",count:1,'
    'components:{"minecraft:unbreakable":{}}}}}'
)


CLEANUP = f"kill @e[tag={TAG}]"
