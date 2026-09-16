"""Guardrail của Bến gắn vào LiteLLM Proxy. Chỉ import được bên trong proxy."""

import copy
import os
from collections.abc import AsyncGenerator
from typing import Any

from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail

from ben_litellm_plugins.governance import decide_routing, normalize_headers, trusted_label
from ben_litellm_plugins.mapping_store import MappingStore, store_from_env
from ben_litellm_plugins.pii import Redactor, restore_response
from ben_litellm_plugins.streaming import StreamRestorer

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
        redactor = Redactor()
        count = redactor.redact_request(data)
        call_id = data.get("litellm_call_id")
        if count and call_id:
            await _mapping_store().put(call_id, redactor.mapping)
        elif count:
            verbose_proxy_logger.warning(
                "ben-pii: đã che nhưng thiếu litellm_call_id, không khôi phục được"
            )
        verbose_proxy_logger.info("ben-pii pre_call call_type=%s redacted=%d", call_type, count)
        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        call_id = data.get("litellm_call_id")
        if not call_id:
            return response
        mapping = await _mapping_store().get(call_id)
        return restore_response(response, mapping)

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response, request_data: dict
    ) -> AsyncGenerator[Any, None]:
        call_id = request_data.get("litellm_call_id")
        mapping = await _mapping_store().get(call_id) if call_id else {}
        if not mapping:
            async for item in response:
                yield item
            return

        restorer = StreamRestorer(mapping)
        last_text_chunk = None
        async for chunk in response:
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
