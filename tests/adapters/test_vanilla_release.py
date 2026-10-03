import json

import pytest
from support.vanilla import JAR_URL, VERSION_URL, FakeMojang, fake_jar, sha1

from mscts.adapters.base import Build, ProvisionError, Release, UnsupportedError
from mscts.adapters.vanilla import MANIFEST_URL, VanillaAdapter
from mscts.target import TARGET

JAR = fake_jar()
RELEASE = Release(build=Build(version="26.3"), url=JAR_URL, sha1=sha1(JAR), size=len(JAR))


@pytest.mark.parametrize("version", [None, "26.3"])
def test_the_target_s_release_is_the_server_jar_mojang_lists_for_it(version: str | None) -> None:
    mojang = FakeMojang()
    assert VanillaAdapter().release(TARGET, version, mojang) == RELEASE
    assert mojang.fetched == [MANIFEST_URL, VERSION_URL]


@pytest.mark.parametrize("version", ["26.4", "26.2", "1.21.8"])
def test_another_version_is_not_supported_and_nothing_is_fetched(version: str) -> None:
    mojang = FakeMojang()
    with pytest.raises(UnsupportedError) as raised:
        VanillaAdapter().release(TARGET, version, mojang)
    assert (
        str(raised.value) == f"vanilla@{version} is not supported: this mscts tests Minecraft 26.3."
    )
    assert mojang.fetched == []


def test_a_version_json_that_is_not_the_one_the_manifest_lists_is_refused() -> None:
    mojang = FakeMojang()
    mojang.bodies[VERSION_URL] += b" "
    with pytest.raises(ProvisionError, match="is not the version JSON"):
        VanillaAdapter().release(TARGET, None, mojang)


def test_a_manifest_without_the_target_is_an_error() -> None:
    mojang = FakeMojang()
    mojang.bodies[MANIFEST_URL] = json.dumps({"versions": []}).encode()
    with pytest.raises(ProvisionError, match=r"lists no 26\.3"):
        VanillaAdapter().release(TARGET, None, mojang)
