from pathlib import Path

import pytest
from support.pumpkin import COMMIT, FakeGitHub, fake_pumpkin, refs

from mscts.adapters.base import Build, ProvisionError, ShortCommitError
from mscts.adapters.fetch import HttpsNet
from mscts.adapters.pumpkin import NIGHTLY_URL, TAGS_URL, PumpkinAdapter
from mscts.target import TARGET

NIGHTLY = Build(version="nightly", commit=COMMIT)


def test_install_puts_the_nightly_at_into_and_names_the_commit_its_tag_names(
    tmp_path: Path,
) -> None:
    github = FakeGitHub()
    into = tmp_path / "pumpkin"
    assert PumpkinAdapter().install(TARGET, None, into, HttpsNet(github)) == NIGHTLY
    assert into.read_bytes() == fake_pumpkin()
    assert github.fetched == [TAGS_URL, NIGHTLY_URL]


# The tag only finds the file: whether the file is the build asked for, only the file says.
@pytest.mark.parametrize(
    "version", ["nightly", COMMIT[:7], COMMIT[:10], COMMIT, "8f3c2a1", "0.2.0+26.3-26.51"]
)
def test_any_version_installs_the_nightly_to_look_at(tmp_path: Path, version: str) -> None:
    github = FakeGitHub()
    into = tmp_path / "pumpkin"
    assert PumpkinAdapter().install(TARGET, version, into, HttpsNet(github)) == NIGHTLY
    assert github.fetched == [TAGS_URL, NIGHTLY_URL]


@pytest.mark.parametrize("version", [COMMIT[:6], COMMIT[:1], "8f3c2a", "4426D1"])
def test_fewer_than_7_characters_of_a_commit_are_refused_before_anything_is_fetched(
    tmp_path: Path, version: str
) -> None:
    said = f"pumpkin@{version} is too short to name a commit: name at least 7 characters of it."
    github = FakeGitHub()
    with pytest.raises(ShortCommitError) as raised:
        PumpkinAdapter().install(TARGET, version, tmp_path / "pumpkin", HttpsNet(github))
    assert str(raised.value) == said
    assert github.fetched == []
    assert list(tmp_path.iterdir()) == []


def test_an_annotated_tag_names_the_commit_it_points_to(tmp_path: Path) -> None:
    annotated = (
        b"001e# service=git-upload-pack\n0000"
        b"003f" + b"f" * 40 + b" refs/tags/nightly\n"
        b"0042" + COMMIT.encode() + b" refs/tags/nightly^{}\n0000"
    )
    net = HttpsNet(FakeGitHub(tags=annotated))
    assert PumpkinAdapter().install(TARGET, None, tmp_path / "pumpkin", net) == NIGHTLY


NO_LIST_OF_REFS = (
    f"{TAGS_URL} did not answer with GitHub's list of git refs (is a proxy in the way?), "
    "so the nightly's commit is unknown."
)


@pytest.mark.parametrize(
    ("tags", "said"),
    [
        (b"<html>Access denied</html>", NO_LIST_OF_REFS),
        (
            refs().replace(b"nightly", b"other"),
            f"{TAGS_URL} has no nightly tag, so the nightly's commit is unknown.",
        ),
    ],
    ids=["no-list-of-refs", "no-nightly-tag"],
)
def test_a_nightly_whose_commit_is_unknown_is_not_downloaded(
    tmp_path: Path, tags: bytes, said: str
) -> None:
    github = FakeGitHub(tags=tags)
    with pytest.raises(ProvisionError) as raised:
        PumpkinAdapter().install(TARGET, None, tmp_path / "pumpkin", HttpsNet(github))
    assert str(raised.value) == said
    assert github.fetched == [TAGS_URL]
    assert list(tmp_path.iterdir()) == []
