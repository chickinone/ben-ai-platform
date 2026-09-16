"""Chuẩn hoá payload logging của LiteLLM thành usage event của Bến (ADR-005)."""

from collections.abc import Mapping
from typing import Any

STREAM_KEY = "stream:usage"


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def build_usage_event(kwargs: Mapping[str, Any]) -> dict[str, str]:
    slo = kwargs.get("standard_logging_object") or {}
    metadata = slo.get("metadata") or {}
    return {
        "call_id": _text(kwargs.get("litellm_call_id") or slo.get("id")),
        "trace_id": _text(slo.get("trace_id")),
        "team_id": _text(metadata.get("user_api_key_team_id")),
        "team_alias": _text(metadata.get("user_api_key_team_alias")),
        "key_hash": _text(metadata.get("user_api_key_hash")),
        "key_alias": _text(metadata.get("user_api_key_alias")),
        "model_group": _text(slo.get("model_group")),
        "model": _text(slo.get("model") or kwargs.get("model")),
        "call_type": _text(slo.get("call_type") or kwargs.get("call_type")),
        "tokens_in": _text(slo.get("prompt_tokens") or 0),
        "tokens_out": _text(slo.get("completion_tokens") or 0),
        "cost_usd": _text(slo.get("response_cost") or kwargs.get("response_cost") or 0),
        "cache_hit": _text(bool(slo.get("cache_hit"))),
        "stream": _text(bool(kwargs.get("stream"))),
        "start_time": _text(slo.get("startTime")),
        "end_time": _text(slo.get("endTime")),
    }
