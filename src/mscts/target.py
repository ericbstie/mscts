"""The Target: the (Minecraft version, protocol version) pair a Run speaks."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Target:
    """A pinned Minecraft version and the protocol and JVM that go with it."""

    minecraft_version: str
    protocol_version: int
    java_major: int  # the Reference's JVM


# ADR-0003. Verified from version.json inside the vanilla 26.3 server jar.
TARGET = Target(minecraft_version="26.3", protocol_version=777, java_major=25)
