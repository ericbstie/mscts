import dataclasses

import pytest

from mscts.net import Endpoint


def test_endpoint_holds_host_and_port() -> None:
    endpoint = Endpoint(host="127.0.0.1", port=25599)
    assert (endpoint.host, endpoint.port) == ("127.0.0.1", 25599)


@pytest.mark.parametrize("field", [field.name for field in dataclasses.fields(Endpoint)])
def test_endpoint_is_frozen(field: str) -> None:
    endpoint = Endpoint(host="127.0.0.1", port=25599)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(endpoint, field, getattr(endpoint, field))


def test_endpoint_has_slots() -> None:
    assert not hasattr(Endpoint(host="127.0.0.1", port=25599), "__dict__")
