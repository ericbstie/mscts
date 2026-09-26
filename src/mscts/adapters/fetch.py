"""Downloading an Installation: HTTPS only, on every hop of every redirect."""

import http.client
import ssl
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, override
from urllib.parse import urlsplit

from mscts.adapters.base import ProvisionError

# How many redirects one fetch may follow. A GitHub release asset takes one.
MAX_REDIRECTS = 5
_FETCH_TIMEOUT_S = 60


@dataclass(frozen=True, slots=True)
class Download:
    """The body of a fetched URL, and the URL it finally came from."""

    url: str  # the final URL, after every redirect
    body: bytes


type Fetch = Callable[[str], Download]


def _require_https(url: str, what: str) -> None:
    if urlsplit(url).scheme != "https":
        msg = f"refusing to {what} a non-HTTPS URL: {url}"
        raise ProvisionError(msg)


class HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follows at most MAX_REDIRECTS redirects, and only to HTTPS URLs."""

    max_redirections = MAX_REDIRECTS

    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """The request for `newurl` (already absolute); ProvisionError if it is not HTTPS."""
        _require_https(newurl, "follow a redirect to")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _https_only_opener() -> urllib.request.OpenerDirector:
    """An opener that can speak nothing but HTTPS: no file:, ftp:, data: or http: handler.

    It honours HTTPS_PROXY and follows redirects only to HTTPS URLs.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        HttpsOnlyRedirects(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


def https_get(url: str) -> Download:
    """GET `url` over HTTPS, following redirects that stay on HTTPS.

    Any other scheme is refused before connecting, and so is a redirect to one.
    """
    _require_https(url, "fetch")
    with _https_only_opener().open(url, timeout=_FETCH_TIMEOUT_S) as response:
        if not isinstance(response, http.client.HTTPResponse):  # urllib types it as Any
            msg = f"unexpected response {type(response).__name__} from {url}"
            raise TypeError(msg)
        final = response.geturl()
        _require_https(final, "accept a response from")
        return Download(url=final, body=response.read())
