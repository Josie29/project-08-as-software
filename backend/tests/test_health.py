import httpx

from app.api.health import DependencyStatus


async def test_health_reports_each_dependency_separately(client: httpx.AsyncClient) -> None:
    """Without per-dependency detail an operator cannot tell a database outage from a
    storage outage, so an uptime alert would be unactionable."""
    response = await client.get("/health")

    body = response.json()
    assert body["app"] == DependencyStatus.OK
    assert body["database"] == DependencyStatus.OK
    assert "storage" in body


async def test_health_returns_503_when_a_dependency_is_unreachable(
    client: httpx.AsyncClient,
) -> None:
    """The uptime check the brief requires keys off the status code alone; if a
    degraded dependency still returned 200, an outage would go unnoticed.

    Storage points at an unreachable local address under test settings.
    """
    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["storage"] == DependencyStatus.DEGRADED
