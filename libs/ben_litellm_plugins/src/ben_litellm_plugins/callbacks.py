"""Callback metering: ghi usage event vào Redis Streams. Chỉ import được bên trong proxy."""

import os
from typing import Any

import redis.asyncio as redis
from litellm.integrations.custom_logger import CustomLogger

from ben_litellm_plugins.metering import STREAM_KEY, build_usage_event


class BenUsageLogger(CustomLogger):
    def __init__(self, redis_url: str | None = None, maxlen: int = 1_000_000) -> None:
        super().__init__()
        self._redis_url = redis_url or os.environ.get("BEN_REDIS_URL", "redis://redis:6379/0")
        self._maxlen = maxlen
        self._client: redis.Redis | None = None

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        if self._client is None:
            self._client = redis.Redis.from_url(self._redis_url, decode_responses=True)
        # redis khai báo kiểu field rộng hơn dict[str, str]; dict là invariant nên cần nới kiểu
        fields: dict[Any, Any] = build_usage_event(kwargs)
        await self._client.xadd(STREAM_KEY, fields, maxlen=self._maxlen, approximate=True)


usage_logger = BenUsageLogger()
