import hashlib
import http.client
import io
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

from mscts.adapters.base import Download, Net, ProvisionError
from mscts.adapters.fetch import (
    MAX_REDIRECTS,
    ChecksumError,
    HttpsNet,
    HttpsOnlyRedirects,
    _https_only_opener,
    https_get,
)

RELEASE = "https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux"
ASSET = "https://release-assets.githubusercontent.com/github-production-release-asset/1/2?sig=x"


def redirect(to: str) -> urllib.request.Request | None:
    """What the redirect policy makes of a 302 from RELEASE to `to`."""
    return HttpsOnlyRedirects().redirect_request(
        urllib.request.Request(RELEASE), io.BytesIO(), 302, "Found", http.client.HTTPMessage(), to
    )


@pytest.mark.parametrize(
    "url", ["file:///etc/hostname", "http://github.com/", "ftp://example.com/x", "data:,x"]
)
def test_https_get_refuses_other_schemes_before_connecting(url: str) -> None:
    with pytest.raises(ProvisionError, match="HTTPS"):
        https_get(url)


def test_a_redirect_to_https_is_followed() -> None:
    request = redirect(ASSET)
    assert request is not None
    assert request.full_url == ASSET


@pytest.mark.parametrize(
    "to", ["http://release-assets.githubusercontent.com/x", "ftp://example.com/x"]
)
def test_a_redirect_off_https_is_refused(to: str) -> None:
    with pytest.raises(ProvisionError, match="HTTPS"):
        redirect(to)


def test_redirect_chains_are_bounded() -> None:
    assert HttpsOnlyRedirects.max_redirections == MAX_REDIRECTS == 5


@pytest.mark.parametrize("url", ["file:///etc/hostname", "ftp://example.com/x", "data:,x"])
def test_the_opener_has_no_handler_for_other_schemes(url: str) -> None:
    # Even a URL that got past every check could not be opened: no file:, ftp: or data:.
    with pytest.raises(urllib.error.URLError, match="unknown url type"):
        _https_only_opener().open(url, timeout=1)


DOCUMENT = "https://publisher.example/latest.json"
BODY = b'{"version": "1.4.0"}'


class FakePublisher:
    """A fetch that serves `bodies` and records every URL asked; RELEASE redirects to ASSET."""

    def __init__(self) -> None:
        self.bodies = {DOCUMENT: BODY, RELEASE: b"\x7fELF build"}
        self.fetched: list[str] = []

    def __call__(self, url: str) -> Download:
        self.fetched.append(url)
        return Download(url=ASSET if url == RELEASE else url, body=self.bodies[url])


def sha1(body: bytes) -> str:
    return hashlib.sha1(body, usedforsecurity=False).hexdigest()


def test_net_gets_a_body_and_parses_a_json_document() -> None:
    net: Net = HttpsNet(FakePublisher())  # ty checks that it is the Net an Adapter gets
    assert net.get(DOCUMENT) == BODY
    assert net.json(DOCUMENT) == {"version": "1.4.0"}
    assert net.json(DOCUMENT, sha1=sha1(BODY)) == {"version": "1.4.0"}


@pytest.mark.parametrize("url", ["http://publisher.example/latest.json", "file:///etc/hostname"])
def test_net_refuses_a_url_that_is_not_https_before_fetching(url: str, tmp_path: Path) -> None:
    publisher = FakePublisher()
    net = HttpsNet(publisher)
    said = f"refusing to fetch a non-HTTPS URL: {url}"
    for call in (net.get, net.json, lambda url: net.download(url, tmp_path / "server")):
        with pytest.raises(ProvisionError) as raised:
            call(url)
        assert str(raised.value) == said
    assert publisher.fetched == []
    assert list(tmp_path.iterdir()) == []


def test_net_refuses_a_json_document_that_is_not_the_one_its_publisher_lists() -> None:
    listed = "0" * 40
    with pytest.raises(ProvisionError) as raised:
        HttpsNet(FakePublisher()).json(DOCUMENT, sha1=listed)
    assert str(raised.value) == (
        f"{DOCUMENT} is not what its publisher lists: sha1 {sha1(BODY)}, where its publisher "
        f"lists sha1 {listed}."
    )


def test_net_downloads_into_a_file(tmp_path: Path) -> None:
    body = FakePublisher().bodies[RELEASE]
    net = HttpsNet(FakePublisher())
    net.download(RELEASE, tmp_path / "server", sha1=sha1(body), size=len(body))
    assert (tmp_path / "server").read_bytes() == body
    HttpsNet(FakePublisher()).download(RELEASE, tmp_path / "unlisted")
    assert (tmp_path / "unlisted").read_bytes() == body


@dataclass(frozen=True)
class Listed:
    id: str
    sha1: str | None
    size: int | None
    said: str  # how the refusal names what the publisher lists


BUILD = b"\x7fELF build"
LISTED = [
    Listed("other-bytes", "1" * 40, len(BUILD), f"sha1 {'1' * 40}, {len(BUILD)} bytes"),
    Listed("longer", sha1(BUILD), len(BUILD) + 1, f"sha1 {sha1(BUILD)}, {len(BUILD) + 1} bytes"),
    Listed("only-sha1", "2" * 40, None, f"sha1 {'2' * 40}"),
    Listed("only-size", None, len(BUILD) - 1, f"{len(BUILD) - 1} bytes"),
]


@pytest.mark.parametrize("listed", LISTED, ids=[listed.id for listed in LISTED])
def test_net_refuses_a_download_that_is_not_the_file_its_publisher_lists(
    tmp_path: Path, listed: Listed
) -> None:
    net = HttpsNet(FakePublisher())
    with pytest.raises(ChecksumError) as raised:
        net.download(RELEASE, tmp_path / "server", sha1=listed.sha1, size=listed.size)
    assert str(raised.value) == (
        f"{RELEASE} is not the file its publisher lists: sha1 {sha1(BUILD)}, {len(BUILD)} bytes, "
        f"where its publisher lists {listed.said}."
    )
    assert isinstance(raised.value, ProvisionError)
    assert list(tmp_path.iterdir()) == []
