import pytest

from mscts.adapters.base import ProvisionError
from mscts.adapters.vanilla import https_get


@pytest.mark.parametrize(
    "url", ["file:///etc/hostname", "http://piston-meta.mojang.com/", "ftp://example.com/x"]
)
def test_https_get_refuses_other_schemes_before_connecting(url: str) -> None:
    with pytest.raises(ProvisionError, match="HTTPS"):
        https_get(url)
