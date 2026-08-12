import httpx
import pytest

from app.config import get_settings
from app.services.storage import (
    ObjectStorage,
    StorageError,
    StorageObjectMissingError,
)


async def test_a_present_object_returns_its_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The image delivery path is the product; if a stored object could not be fetched,
    no patient would ever see a scan."""
    payload = b"\xff\xd8\xff-jpeg-bytes"
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        _stub_get(httpx.Response(200, content=payload)),
    )

    result = await ObjectStorage(get_settings()).download("studies/x/images/y.jpg")

    assert result == payload


async def test_a_missing_object_is_distinguished_from_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cine manifest may legitimately reference a frame that is absent. That has to be
    tellable apart from storage being down, or the viewer cannot degrade around a gap
    while still reporting a real outage (edge case #2)."""
    monkeypatch.setattr(httpx.AsyncClient, "get", _stub_get(httpx.Response(400)))

    with pytest.raises(StorageObjectMissingError):
        await ObjectStorage(get_settings()).download("studies/x/gone.jpg")


async def test_an_unexpected_status_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 500 from storage must not be reported to the patient as 'no such image' — that
    would hide an outage behind a message implying their data is gone."""
    monkeypatch.setattr(httpx.AsyncClient, "get", _stub_get(httpx.Response(500)))

    with pytest.raises(StorageError):
        await ObjectStorage(get_settings()).download("studies/x/y.jpg")


async def test_a_transport_failure_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """If storage is unreachable the request must fail cleanly rather than raising an
    unhandled exception that surfaces as a 500 with a stack trace."""

    async def boom(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)

    with pytest.raises(StorageError):
        await ObjectStorage(get_settings()).download("studies/x/y.jpg")


def _stub_get(response: httpx.Response):
    """Return an AsyncClient.get replacement yielding a fixed response.

    Args:
        response: The response to return.

    Returns:
        An async callable suitable for monkeypatching.
    """

    async def _get(*args: object, **kwargs: object) -> httpx.Response:
        return response

    return _get
