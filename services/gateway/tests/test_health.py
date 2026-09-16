import asyncio

from fastapi.testclient import TestClient

from ben_gateway.config import GatewaySettings
from ben_gateway.main import create_app


async def ok_check() -> None:
    return None


async def failing_check() -> None:
    raise ConnectionError("password=super-secret host=postgres")


async def slow_check() -> None:
    await asyncio.sleep(1)


def client_with(checks, **settings_overrides) -> TestClient:
    settings = GatewaySettings(**settings_overrides)
    return TestClient(create_app(settings, checks=checks))


def test_healthz_returns_ok():
    with client_with({}) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ok_when_all_dependencies_respond():
    with client_with({"postgres": ok_check, "redis": ok_check}) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}


def test_readyz_reports_failure_without_leaking_error_details():
    with client_with({"postgres": ok_check, "redis": failing_check}) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": "ok", "redis": "error: ConnectionError"}
    assert "super-secret" not in response.text


def test_readyz_marks_slow_dependency_as_timeout():
    with client_with({"postgres": slow_check}, readiness_timeout_s=0.05) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": "timeout"}


def test_unknown_route_uses_common_error_format():
    with client_with({}) as client:
        response = client.get("/khong-ton-tai")
    body = response.json()
    assert response.status_code == 404
    assert body["error"]["type"] == "not_found"
    assert body["error"]["trace_id"] == response.headers["X-Request-Id"]


def test_valid_request_id_is_echoed():
    with client_with({}) as client:
        response = client.get("/healthz", headers={"X-Request-Id": "req-12345678"})
    assert response.headers["X-Request-Id"] == "req-12345678"


def test_invalid_request_id_is_replaced():
    with client_with({}) as client:
        response = client.get("/healthz", headers={"X-Request-Id": "bad id!"})
    request_id = response.headers["X-Request-Id"]
    assert request_id != "bad id!"
    assert len(request_id) == 32
