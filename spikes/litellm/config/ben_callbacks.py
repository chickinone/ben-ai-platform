"""Callback metering thử nghiệm: ghi usage event vào Redis Streams (ADR-005).

Đồng thời ghi lại việc payload logging mà LiteLLM đưa cho callback có chứa SĐT thô không —
đây chính là payload mà các tích hợp như Langfuse nhận được.
"""

import json
import os
import re
from typing import Any

import redis.asyncio as redis
from litellm.integrations.custom_logger import CustomLogger

STREAM = "stream:ben-usage-spike"
PHONE_RE = re.compile(r"(?<!\d)(?:\+84|0)(?:[\s.]?\d){9}(?!\d)")


def _contains_phone(value: Any) -> bool:
    try:
        return bool(PHONE_RE.search(json.dumps(value, ensure_ascii=False, default=str)))
    except (TypeError, ValueError):
        return False


class BenUsageLogger(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        self._redis: redis.Redis | None = None

    def _client(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.Redis(
                host=os.environ.get("BEN_REDIS_HOST", "redis"), port=6379, decode_responses=True
            )
        return self._redis

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        slo = kwargs.get("standard_logging_object") or {}
        fields = {
            "call_id": str(kwargs.get("litellm_call_id") or ""),
            "slo_id": str(slo.get("id") or ""),
            "model_group": str(slo.get("model_group") or ""),
            "model": str(slo.get("model") or kwargs.get("model") or ""),
            "call_type": str(slo.get("call_type") or kwargs.get("call_type") or ""),
            "tokens_in": str(slo.get("prompt_tokens") or 0),
            "tokens_out": str(slo.get("completion_tokens") or 0),
            "cost_usd": str(slo.get("response_cost") or kwargs.get("response_cost") or 0),
            "cache_hit": str(slo.get("cache_hit")),
            "stream": str(bool(kwargs.get("stream"))),
            "raw_phone_in_messages": str(_contains_phone(slo.get("messages"))),
            "raw_phone_in_response": str(_contains_phone(slo.get("response"))),
        }
        await self._client().xadd(STREAM, fields, maxlen=10000, approximate=True)


usage_logger = BenUsageLogger()
