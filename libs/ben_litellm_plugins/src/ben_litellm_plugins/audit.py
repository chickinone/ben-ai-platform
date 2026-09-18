"""Phát audit event không chứa prompt hoặc PII thô sang Redis Streams."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import redis.asyncio as redis
from litellm._logging import verbose_proxy_logger

STREAM_KEY = "stream:guardrail"


class GuardrailAuditLogger:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or os.environ.get("BEN_REDIS_URL", "redis://redis:6379/0")
        self._client: redis.Redis | None = None

    async def record(
        self,
        user_api_key_dict: Any,
        *,
        action: str,
        call_id: str | None,
        detail: dict[str, Any],
    ) -> None:
        if self._client is None:
            self._client = redis.Redis.from_url(self._redis_url, decode_responses=True)
        metadata = getattr(user_api_key_dict, "metadata", None) or {}
        # Chỉ đưa metadata server cấp vào audit; tuyệt đối không ghi text/evidence prompt.
        fields: dict[Any, Any] = {
            "ts": str(time.time()),
            "actor": f"tenant:{metadata.get('ben_tenant', 'unknown')}",
            "action": action,
            "resource": f"request:{call_id or 'unknown'}",
            "team_id": str(getattr(user_api_key_dict, "team_id", "") or ""),
            "detail": json.dumps(detail, ensure_ascii=False, sort_keys=True),
        }
        try:
            await self._client.xadd(STREAM_KEY, fields, maxlen=1_000_000, approximate=True)
        except Exception:
            # Audit lỗi không biến một request đã được kiểm soát thành lỗi 5xx; log không có PII.
            verbose_proxy_logger.exception("ben-audit: không phát được guardrail audit event")


audit_logger = GuardrailAuditLogger()
