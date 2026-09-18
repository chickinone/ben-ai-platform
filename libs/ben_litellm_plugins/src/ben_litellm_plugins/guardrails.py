"""Guardrail của Bến gắn vào LiteLLM Proxy. Chỉ import được bên trong proxy."""

import copy
import os
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as redis
from fastapi import HTTPException
from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail

from ben_litellm_plugins.audit import audit_logger
from ben_litellm_plugins.governance import decide_routing, normalize_headers, trusted_label
from ben_litellm_plugins.mapping_store import MappingStore, store_from_env
from ben_litellm_plugins.pii import Redactor, mask_response, restore_response
from ben_litellm_plugins.rate_limits import consume_request
from ben_litellm_plugins.rate_limits import policy_from_metadata as rate_policy
from ben_litellm_plugins.streaming import StreamRestorer, restore_anthropic_sse_chunk
from ben_pii_vn import PiiMode, detect_prompt_injection
from ben_pii_vn.policy import policy_from_metadata as pii_policy

_store: MappingStore | None = None


def _mapping_store() -> MappingStore:
    global _store
    if _store is None:
        _store = store_from_env()
    return _store


def _chunk_text(chunk: Any) -> str | None:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return None
    content = getattr(getattr(choices[0], "delta", None), "content", None)
    return content if isinstance(content, str) else None


def _set_chunk_text(chunk: Any, text: str) -> bool:
    choices = getattr(chunk, "choices", None)
    delta = getattr(choices[0], "delta", None) if choices else None
    if delta is None:
        return False
    delta.content = text
    return True


class BenPIIGuardrail(CustomGuardrail):
    """Che định danh trước khi gửi provider, khôi phục ở response (thường + streaming)."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        policy = pii_policy(getattr(user_api_key_dict, "metadata", None))
        if policy.mode is PiiMode.OFF:
            return data
        redactor = Redactor()
        count = redactor.redact_request(data)
        call_id = data.get("litellm_call_id")
        if count and policy.mode is PiiMode.BLOCK:
            await audit_logger.record(
                user_api_key_dict,
                action="guardrail.pii_blocked",
                call_id=call_id,
                detail={
                    "count": count,
                    "kinds": sorted({key.split("_")[0][1:] for key in redactor.mapping}),
                },
            )
            raise HTTPException(
                status_code=400,
                detail={"error": {"message": "Request chứa dữ liệu cá nhân theo policy tenant"}},
            )
        if count and call_id and policy.restore:
            await _mapping_store().put(call_id, redactor.mapping)
        if count:
            await audit_logger.record(
                user_api_key_dict,
                action="guardrail.pii_redacted",
                call_id=call_id,
                detail={"count": count, "mode": policy.mode.value},
            )
        if count and not call_id:
            verbose_proxy_logger.warning(
                "ben-pii: đã che nhưng thiếu litellm_call_id, không khôi phục được"
            )
        verbose_proxy_logger.info("ben-pii pre_call call_type=%s redacted=%d", call_type, count)
        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        policy = pii_policy(getattr(user_api_key_dict, "metadata", None))
        if policy.mode is PiiMode.OFF:
            return response
        call_id = data.get("litellm_call_id")
        mapping = await _mapping_store().get(call_id) if call_id and policy.restore else {}
        if policy.restore:
            restore_response(response, mapping)
        # Chỉ miễn che những giá trị người dùng đã gửi và policy cho phép khôi phục.
        return mask_response(response, set(mapping.values()) if policy.restore else None)

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response, request_data: dict
    ) -> AsyncGenerator[Any, None]:
        policy = pii_policy(getattr(user_api_key_dict, "metadata", None))
        if policy.mode is PiiMode.OFF or not policy.restore:
            async for item in response:
                yield item
            return
        call_id = request_data.get("litellm_call_id")
        mapping = await _mapping_store().get(call_id) if call_id else {}
        if not mapping:
            async for item in response:
                yield item
            return

        restorer = StreamRestorer(mapping)
        last_text_chunk = None
        async for chunk in response:
            # LiteLLM chuyển Anthropic /v1/messages sang raw SSE bytes/str tại đây,
            # không phải OpenAI choices/delta object.
            if isinstance(chunk, (str, bytes)):
                yield restore_anthropic_sse_chunk(chunk, restorer)
                continue
            text = _chunk_text(chunk)
            if text is None:
                if restorer.has_pending:
                    _set_chunk_text(chunk, restorer.flush())
                yield chunk
                continue
            _set_chunk_text(chunk, restorer.feed(text))
            last_text_chunk = chunk
            yield chunk

        if restorer.has_pending and last_text_chunk is not None:
            tail = copy.deepcopy(last_text_chunk)
            _set_chunk_text(tail, restorer.flush())
            yield tail


def _request_text(data: Any) -> str:
    """Lấy text không tin cậy từ body request, không quét model/key/metadata."""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return "\n".join(_request_text(item) for item in data)
    if isinstance(data, dict):
        return "\n".join(
            _request_text(value)
            for name, value in data.items()
            if name in {"messages", "system", "content", "text", "input", "prompt"}
        )
    return ""


class BenInjectionGuardrail(CustomGuardrail):
    """Chặn heuristic injection tín hiệu cao trước khi request đến provider."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        metadata = getattr(user_api_key_dict, "metadata", None) or {}
        mode = str(metadata.get("ben_injection_mode", "block")).lower()
        if mode != "block":
            return data
        findings = detect_prompt_injection(_request_text(data))
        if findings:
            rules = ", ".join(finding.rule for finding in findings)
            await audit_logger.record(
                user_api_key_dict,
                action="guardrail.injection_blocked",
                call_id=data.get("litellm_call_id"),
                detail={"rules": [finding.rule for finding in findings]},
            )
            raise HTTPException(
                status_code=400,
                detail={"error": {"message": f"Prompt injection bị chặn ({rules})"}},
            )
        return data


class BenGovernanceGuardrail(CustomGuardrail):
    """Nhãn Confidential/Restricted (chỉ tin từ key dịch vụ nội bộ) → model local, tắt fallback."""

    _local_models = frozenset(
        m.strip() for m in os.environ.get("BEN_LOCAL_MODELS", "").split(",") if m.strip()
    )
    _default_local_model = os.environ.get("BEN_DEFAULT_LOCAL_MODEL", "")

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        key_metadata = getattr(user_api_key_dict, "metadata", None)
        label = trusted_label(normalize_headers(data), key_metadata)
        if label is None:
            return data
        decision = decide_routing(
            data.get("model", ""), label, self._local_models, self._default_local_model
        )
        if decision.disable_fallbacks:
            if not decision.model:
                raise ValueError("BEN_DEFAULT_LOCAL_MODEL chưa cấu hình: không thể ép model local")
            verbose_proxy_logger.info(
                "ben-governance %s model %s -> %s",
                decision.reason,
                data.get("model"),
                decision.model,
            )
            data["model"] = decision.model
            data["disable_fallbacks"] = True
        return data


class BenSharedRateLimitGuardrail(CustomGuardrail):
    """Chặn RPM/TPM ở Redis để quota không bị nhân đôi khi proxy có nhiều worker.

    Metadata được gắn khi cấp virtual key; caller không thể đặt hay sửa nó qua header.
    Khi Redis không khả dụng, chọn fail-closed để không tạo burst đột ngột tới provider.
    """

    def __init__(self, *args, **kwargs) -> None:
        # LiteLLM injects guardrail_name khi nạp từ config.yaml.
        super().__init__(*args, **kwargs)
        self._redis_url = os.environ.get("BEN_REDIS_URL", "redis://redis:6379/0")
        self._client: redis.Redis | None = None

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        metadata = getattr(user_api_key_dict, "metadata", None)
        policy = rate_policy(metadata)
        if policy is None:
            return data
        if self._client is None:
            self._client = redis.Redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        try:
            # Giữ nguyên tuple: giải nén sớm sẽ làm mất liên hệ giữa hai phần tử,
            # khiến trình kiểm kiểu không biết ``reason`` luôn có giá trị khi bị từ chối.
            outcome = await consume_request(self._client, policy, data)
        except Exception as exc:
            verbose_proxy_logger.exception("ben-rate-limit: Redis không khả dụng")
            raise HTTPException(
                status_code=503,
                detail={"error": {"message": "Rate limiter tạm thời không khả dụng"}},
            ) from exc
        if not outcome[0]:
            reason = outcome[1]
            limit = policy.rpm if reason == "rpm" else policy.tpm
            raise HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "message": f"Tenant vượt giới hạn {reason.upper()} mỗi phút ({limit})",
                        "type": "rate_limit_exceeded",
                    }
                },
                headers={"Retry-After": "60"},
            )
        return data
