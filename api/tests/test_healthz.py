import httpx

from app.version import APP_VERSION


async def test_healthz_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/healthz")
    assert resp.status_code == 200
    # Exact match, not a subset: healthz is a liveness probe and its shape is a
    # contract with docker-compose's healthcheck and the e2e/smoke wait loops.
    assert resp.json() == {"status": "ok", "version": APP_VERSION}


async def test_healthz_reports_a_version(client: httpx.AsyncClient) -> None:
    """Unset APP_VERSION must still yield something, not an empty string.

    An image built without --build-arg would otherwise report "" and look like a
    field that exists but never got populated.
    """
    resp = await client.get("/api/v1/healthz")
    assert resp.json()["version"]
