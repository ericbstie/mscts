"""Groups for the tests of registering, running and checking Groups."""

from mscts.group import GroupContext


async def nothing(_: GroupContext) -> None:
    pass
