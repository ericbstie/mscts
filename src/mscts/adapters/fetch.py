"""Downloading an Installation: HTTPS only, on every hop of every redirect."""

import hashlib
import http.client
import json
import ssl
import urllib.request
from pathlib import Path
from typing import IO, Any, override
from urllib.parse import urlsplit

from mscts.adapters.base import Download, Fetch, ProvisionError

# How many redirects one fetch may follow. A GitHub release asset takes one.
MAX_REDIRECTS = 5
_FETCH_TIMEOUT_S = 60


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


class ChecksumError(ProvisionError):
    """A download that is not the file its publisher lists: mscts says how to run it anyway."""


def _sha1(body: bytes) -> str:
    """The publisher's own hash of `body` (Mojang's): an integrity check, not security."""
    return hashlib.sha1(body, usedforsecurity=False).hexdigest()


def _listed(sha1: str | None, size: int | None) -> str:
    """What a publisher lists for a file, in words: `sha1 <hex>, <n> bytes`, or either."""
    parts = [] if sha1 is None else [f"sha1 {sha1}"]
    return ", ".join(parts if size is None else [*parts, f"{size} bytes"])


class HttpsNet:
    """The Net mscts hands an Adapter, built on a Fetch (https_get, or a fake in tests)."""

    def __init__(self, fetch: Fetch = https_get) -> None:
        """Read every URL through `fetch`, which may announce it."""
        self._fetch = fetch

    def _read(self, url: str) -> Download:
        """`url` fetched; ProvisionError, before fetching, unless it is HTTPS."""
        _require_https(url, "fetch")
        return self._fetch(url)

    def get(self, url: str, sha1: str | None = None) -> bytes:
        """The body at `url`; ProvisionError unless its sha1 is `sha1`, where one is given."""
        body = self._read(url).body
        if sha1 is not None and _sha1(body) != sha1:
            msg = (
                f"{url} is not what its publisher lists: sha1 {_sha1(body)}, where its "
                f"publisher lists sha1 {sha1}."
            )
            raise ProvisionError(msg)
        return body

    def json(self, url: str, sha1: str | None = None) -> Any:  # noqa: ANN401 - the publisher's shape
        """The JSON document at `url`, parsed, checked as `get` checks it."""
        return json.loads(self.get(url, sha1))

    def download(
        self, url: str, into: Path, sha1: str | None = None, size: int | None = None
    ) -> None:
        """Save the body at `url` as `into`; ChecksumError unless it has the sha1 and size given."""
        body = self._read(url).body
        if (sha1 is not None and _sha1(body) != sha1) or (size is not None and len(body) != size):
            msg = (
                f"{url} is not the file its publisher lists: sha1 {_sha1(body)}, {len(body)} "
                f"bytes, where its publisher lists {_listed(sha1, size)}."
            )
            raise ChecksumError(msg)
        into.write_bytes(body)
