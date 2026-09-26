import http.client
import io
import urllib.error
import urllib.request

import pytest

from mscts.adapters.base import ProvisionError
from mscts.adapters.fetch import (
    MAX_REDIRECTS,
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
