import pytest
from support.pumpkin import COMMIT

from mscts.adapters.base import Build, Download, ProvisionError, Release
from mscts.adapters.pumpkin import NIGHTLY_URL, TAGS_URL, PumpkinAdapter
from mscts.target import TARGET

# The start of GitHub's ref advertisement (pkt-lines), as `git ls-remote` reads it.
REFS = (
    b"001e# service=git-upload-pack\n0000"
    b"015b1859221e7ad1227f43277f74507f921c0acec83f HEAD\0multi_ack symref=HEAD:refs/heads/master\n"
    b"003f1859221e7ad1227f43277f74507f921c0acec83f refs/heads/master\n"
    b"003f" + COMMIT.encode() + b" refs/tags/nightly\n"
    b"0000"
)


class FakeGitHub:
    """A fetch that serves the ref advertisement and records every URL asked."""

    def __init__(self, refs: bytes = REFS) -> None:
        self.refs = refs
        self.fetched: list[str] = []

    def __call__(self, url: str) -> Download:
        self.fetched.append(url)
        return Download(url=url, body=self.refs)


NIGHTLY = Release(build=Build(version="nightly", commit=COMMIT), url=NIGHTLY_URL)


def test_the_latest_build_is_the_nightly_at_the_commit_its_tag_names() -> None:
    github = FakeGitHub()
    assert PumpkinAdapter().release(TARGET, None, github) == NIGHTLY
    assert github.fetched == [TAGS_URL]


@pytest.mark.parametrize("version", [COMMIT[:7], COMMIT[:10], COMMIT])
def test_the_nightly_s_commit_names_the_nightly(version: str) -> None:
    assert PumpkinAdapter().release(TARGET, version, FakeGitHub()) == NIGHTLY


@pytest.mark.parametrize("version", ["8f3c2a1", COMMIT[:6], "0.2.0+26.3-26.51"])
def test_any_other_build_is_not_available_and_says_how_to_build_it(version: str) -> None:
    said = (
        f"pumpkin@{version} is not available: Pumpkin only publishes its latest nightly "
        "(now 4426d11).\n"
        "Build it yourself and install it with:\n"
        "  uv run mscts adapter install pumpkin --from <file>"
    )
    with pytest.raises(ProvisionError) as raised:
        PumpkinAdapter().release(TARGET, version, FakeGitHub())
    assert str(raised.value) == said


def test_an_annotated_tag_names_the_commit_it_points_to() -> None:
    annotated = (
        b"003f" + b"f" * 40 + b" refs/tags/nightly\n"
        b"0042" + COMMIT.encode() + b" refs/tags/nightly^{}\n0000"
    )
    assert PumpkinAdapter().release(TARGET, None, FakeGitHub(annotated)) == NIGHTLY


def test_no_nightly_tag_is_an_error_naming_the_from_command() -> None:
    with pytest.raises(ProvisionError, match=r"no nightly tag(.|\n)*--from <file>"):
        PumpkinAdapter().release(TARGET, None, FakeGitHub(REFS.replace(b"nightly", b"other")))
