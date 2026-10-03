"""Stand-ins for Pumpkin's binaries and for GitHub, which publishes them: never run."""

from mscts.adapters.base import Download
from mscts.adapters.pumpkin import NIGHTLY_URL, TAGS_URL

COMMIT = "4426d1113a211e6018a2db416e33b6b8a7802614"
# Where GitHub redirects NIGHTLY_URL to.
ASSET_URL = "https://release-assets.githubusercontent.com/github-production-release-asset/1/2?sig=s"


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


def refs(commit: str = COMMIT) -> bytes:
    """The start of GitHub's ref advertisement (pkt-lines), its `nightly` tag at `commit`."""
    return (
        b"001e# service=git-upload-pack\n0000"
        b"015b1859221e7ad1227f43277f74507f921c0acec83f HEAD\0multi_ack symref=HEAD:refs/heads/"
        b"master\n003f1859221e7ad1227f43277f74507f921c0acec83f refs/heads/master\n"
        b"003f" + commit.encode() + b" refs/tags/nightly\n0000"
    )


class FakeGitHub:
    """A fetch that serves the nightly's tag and its binary, and records every URL asked."""

    def __init__(self, binary: bytes | None = None, tags: bytes | None = None) -> None:
        self.bodies = {
            TAGS_URL: refs() if tags is None else tags,
            NIGHTLY_URL: fake_pumpkin() if binary is None else binary,
        }
        self.fetched: list[str] = []

    def __call__(self, url: str) -> Download:
        self.fetched.append(url)
        return Download(url=ASSET_URL if url == NIGHTLY_URL else url, body=self.bodies[url])
