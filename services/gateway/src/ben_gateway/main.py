from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from ben_common.errors import install_error_handlers
from ben_common.logging import configure_logging
from ben_common.request_id import install_request_id
from ben_gateway import __version__
from ben_gateway.config import GatewaySettings
from ben_gateway.health import Check, postgres_check, redis_check, run_checks


def create_app(
    settings: GatewaySettings | None = None,
    checks: Mapping[str, Check] | None = None,
) -> FastAPI:
    """Tạo ứng dụng gateway.

    `checks` cho phép test thay các kiểm tra phụ thuộc thật bằng hàm giả.
    Chạy thật:  uvicorn ben_gateway.main:create_app --factory
    """
    settings = settings or GatewaySettings()
    configure_logging(settings.log_level, settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if checks is not None:
            app.state.checks = checks
            yield
            return
        redis_client = Redis.from_url(settings.redis_url)
        app.state.checks = {
            "postgres": postgres_check(settings.database_url),
            "redis": redis_check(redis_client),
        }
        try:
            yield
        finally:
            await redis_client.aclose()

    app = FastAPI(title="Bến AI Gateway", version=__version__, lifespan=lifespan)
    install_request_id(app)
    install_error_handlers(app)

    if settings.otel_enabled:
        from ben_telemetry import setup_telemetry

        setup_telemetry(app, settings.service_name, settings.otel_endpoint)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness: tiến trình còn chạy."""
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(request: Request) -> JSONResponse:
        """Readiness: các phụ thuộc bắt buộc đều phản hồi."""
        results = await run_checks(request.app.state.checks, settings.readiness_timeout_s)
        healthy = all(result == "ok" for result in results.values())
        return JSONResponse(
            {"status": "ok" if healthy else "degraded", "checks": results},
            status_code=200 if healthy else 503,
        )

    return app
