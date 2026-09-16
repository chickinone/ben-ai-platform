import asyncio
from collections.abc import Awaitable, Callable, Mapping

import psycopg
from redis.asyncio import Redis

Check = Callable[[], Awaitable[None]]


async def run_checks(checks: Mapping[str, Check], timeout_s: float) -> dict[str, str]:
    """Chạy song song các kiểm tra phụ thuộc.

    Chỉ trả tên lỗi, không trả thông điệp lỗi — thông điệp của driver có thể chứa
    connection string hoặc mật khẩu.
    """

    async def run_one(check: Check) -> str:
        try:
            await asyncio.wait_for(check(), timeout=timeout_s)
        except TimeoutError:
            return "timeout"
        except Exception as exc:
            return f"error: {type(exc).__name__}"
        return "ok"

    names = list(checks)
    results = await asyncio.gather(*(run_one(checks[name]) for name in names))
    return dict(zip(names, results, strict=True))


def postgres_check(database_url: str) -> Check:
    async def check() -> None:
        connection = await psycopg.AsyncConnection.connect(database_url, connect_timeout=2)
        async with connection:
            await connection.execute("SELECT 1")

    return check


def redis_check(client: Redis) -> Check:
    async def check() -> None:
        await client.ping()

    return check
