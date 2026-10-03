"""Stand-ins for Pumpkin binaries: never run, only checked and installed."""

COMMIT = "4426d1113a211e6018a2db416e33b6b8a7802614"


def fake_pumpkin(
    version: str = "0.2.0+26.3-26.51", commit: str = COMMIT, tail: bytes = b""
) -> bytes:
    """An ELF header, then the strings a Pumpkin build holds, then `tail` (another build).

    The compiler folds `"{version} (Commit: {short}/"` into one string, and keeps the full
    commit right after a second short one (docs/research/2026-10-03-install.md).
    """
    short = commit[:7] if commit != "unknown" else commit
    strings = f"Spawn {version} (Commit: {short}/ Player {short}{commit}pumpkin:commands"
    return b"\x7fELF\x02\x01\x01\x00" + bytes(64) + strings.encode() + bytes(64) + tail
