import pytest
from support.pumpkin import COMMIT, FakeGitHub, refs

from mscts.adapters.base import Build, ProvisionError, Release
from mscts.adapters.pumpkin import NIGHTLY_URL, TAGS_URL, PumpkinAdapter
from mscts.target import TARGET

REFS = refs()


NIGHTLY = Release(build=Build(version="nightly", commit=COMMIT), url=NIGHTLY_URL)


def test_the_latest_build_is_the_nightly_at_the_commit_its_tag_names() -> None:
    github = FakeGitHub()
    assert PumpkinAdapter().release(TARGET, None, github) == NIGHTLY
    assert github.fetched == [TAGS_URL]


@pytest.mark.parametrize("version", ["nightly", COMMIT[:7], COMMIT[:10], COMMIT])
def test_the_nightly_s_commit_names_the_nightly(version: str) -> None:
    assert PumpkinAdapter().release(TARGET, version, FakeGitHub()) == NIGHTLY


# The tag only finds the file: whether the file is the build asked for, only the file says.
@pytest.mark.parametrize("version", ["8f3c2a1", "0.2.0+26.3-26.51"])
def test_any_other_version_is_still_the_nightly_to_look_at(version: str) -> None:
    github = FakeGitHub()
    assert PumpkinAdapter().release(TARGET, version, github) == NIGHTLY
    assert github.fetched == [TAGS_URL]


@pytest.mark.parametrize("version", [COMMIT[:6], COMMIT[:1], "8f3c2a"])
def test_fewer_than_7_characters_of_a_commit_are_too_short_to_name_one(version: str) -> None:
    said = f"pumpkin@{version} is too short to name a commit: name at least 7 characters of it."
    github = FakeGitHub()
    with pytest.raises(ProvisionError) as raised:
        PumpkinAdapter().release(TARGET, version, github)
    assert str(raised.value) == said
    assert github.fetched == []


def test_an_annotated_tag_names_the_commit_it_points_to() -> None:
    annotated = (
        b"001e# service=git-upload-pack\n0000"
        b"003f" + b"f" * 40 + b" refs/tags/nightly\n"
        b"0042" + COMMIT.encode() + b" refs/tags/nightly^{}\n0000"
    )
    assert PumpkinAdapter().release(TARGET, None, FakeGitHub(tags=annotated)) == NIGHTLY


def test_a_page_that_is_no_list_of_git_refs_is_not_blamed_on_pumpkin() -> None:
    said = (
        f"{TAGS_URL} did not answer with GitHub's list of git refs (is a proxy in the way?), "
        "so the nightly's commit is unknown."
    )
    with pytest.raises(ProvisionError) as raised:
        PumpkinAdapter().release(TARGET, None, FakeGitHub(tags=b"<html>Access denied</html>"))
    assert str(raised.value) == said


def test_no_nightly_tag_is_an_error_of_facts_only() -> None:
    with pytest.raises(ProvisionError) as raised:
        PumpkinAdapter().release(TARGET, None, FakeGitHub(tags=REFS.replace(b"nightly", b"other")))
    assert str(raised.value) == (
        f"{TAGS_URL} has no nightly tag, so the nightly's commit is unknown."
    )
