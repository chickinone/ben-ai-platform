"""Guardrail thử nghiệm của Bến cắm vào LiteLLM Proxy.

Code spike — chỉ đủ để trả lời câu hỏi "LiteLLM có đáp ứng yêu cầu của Bến không".
- BenPIIGuardrail: che SĐT trước khi gửi provider, khôi phục ở response (thường + streaming).
- BenGovernanceGuardrail: giả lập quyết định OPA — context Confidential phải dùng model local.
"""

import copy
import re
import time
from collections.abc import AsyncGenerator
from typing import Any

from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail

PHONE_RE = re.compile(r"(?<!\d)(?:\+84|0)(?:[\s.]?\d){9}(?!\d)")
MAX_PLACEHOLDER_LEN = len("<PHONE_9999>")
LOCAL_MODELS = {"local-small"}
CONFIDENTIAL_LABELS = {"confidential", "restricted"}

# Bảng ánh xạ placeholder → giá trị gốc, chỉ nằm trong RAM của tiến trình proxy.
# Spike chạy 1 worker; nhiều worker cần kho dùng chung (sẽ ghi vào kết luận).
_MAPPINGS: dict[str, tuple[float, dict[str, str]]] = {}
_TTL_S = 600


def _headers(data: dict) -> dict[str, str]:
    candidates = [
        (data.get("proxy_server_request") or {}).get("headers"),
        data.get("headers"),
        (data.get("metadata") or {}).get("headers"),
        (data.get("litellm_metadata") or {}).get("headers"),
    ]
    merged: dict[str, str] = {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            merged.update({str(k).lower(): str(v) for k, v in candidate.items()})
    return merged


def _correlation_key(data: dict) -> str | None:
    return data.get("litellm_call_id")


def _store(key: str, mapping: dict[str, str]) -> None:
    now = time.monotonic()
    for stale in [k for k, (ts, _) in _MAPPINGS.items() if now - ts > _TTL_S]:
        _MAPPINGS.pop(stale, None)
    _MAPPINGS[key] = (now, mapping)


def _load(key: str | None) -> dict[str, str]:
    if not key or key not in _MAPPINGS:
        return {}
    return _MAPPINGS[key][1]


def _restore(text: str, mapping: dict[str, str]) -> str:
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


class _Redactor:
    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}
        self._reverse: dict[str, str] = {}

    def text(self, value: str) -> str:
        def replace(match: re.Match) -> str:
            original = match.group(0)
            if original not in self._reverse:
                placeholder = f"<PHONE_{len(self.mapping) + 1}>"
                self.mapping[placeholder] = original
                self._reverse[original] = placeholder
            return self._reverse[original]

        return PHONE_RE.sub(replace, value)

    def content(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            for part in value:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    part["text"] = self.text(part["text"])
        return value


def _split_safe(buffer: str) -> tuple[str, str]:
    """Giữ lại phần đuôi có thể là placeholder chưa trọn (ví dụ '<PHO')."""
    index = buffer.rfind("<")
    if index != -1 and ">" not in buffer[index:] and len(buffer) - index < MAX_PLACEHOLDER_LEN:
        return buffer[:index], buffer[index:]
    return buffer, ""


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
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        redactor = _Redactor()
        for message in data.get("messages") or []:
            if isinstance(message, dict) and "content" in message:
                message["content"] = redactor.content(message["content"])
        if "system" in data:
            data["system"] = redactor.content(data["system"])

        key = _correlation_key(data)
        if redactor.mapping and key:
            _store(key, redactor.mapping)
        verbose_proxy_logger.info(
            "ben-pii pre_call call_type=%s redacted=%d has_call_id=%s",
            call_type,
            len(redactor.mapping),
            bool(key),
        )
        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        mapping = _load(_correlation_key(data))
        if not mapping:
            return response

        choices = getattr(response, "choices", None)
        if choices:
            for choice in choices:
                message = getattr(choice, "message", None)
                if message is not None and isinstance(getattr(message, "content", None), str):
                    message.content = _restore(message.content, mapping)
            return response

        blocks = response.get("content") if isinstance(response, dict) else None
        if blocks is None:
            blocks = getattr(response, "content", None)
        for block in blocks or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                block["text"] = _restore(block["text"], mapping)
            elif isinstance(getattr(block, "text", None), str):
                block.text = _restore(block.text, mapping)
        return response

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response, request_data: dict
    ) -> AsyncGenerator[Any, None]:
        mapping = _load(_correlation_key(request_data))
        if not mapping:
            async for item in response:
                yield item
            return

        buffer = ""
        last_text_chunk = None
        async for chunk in response:
            text = _chunk_text(chunk)
            if text is None:
                if buffer and _set_chunk_text(chunk, _restore(buffer, mapping)):
                    buffer = ""
                yield chunk
                continue
            safe, buffer = _split_safe(buffer + text)
            _set_chunk_text(chunk, _restore(safe, mapping))
            last_text_chunk = chunk
            yield chunk

        if buffer and last_text_chunk is not None:
            tail = copy.deepcopy(last_text_chunk)
            _set_chunk_text(tail, _restore(buffer, mapping))
            yield tail


class BenGovernanceGuardrail(CustomGuardrail):
    """Giả lập OPA: nhãn context lấy từ header (spike bỏ qua ranh giới tin cậy)."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        label = _headers(data).get("x-ben-context-label", "internal").lower()
        if label in CONFIDENTIAL_LABELS:
            original_model = data.get("model")
            if original_model not in LOCAL_MODELS:
                data["model"] = "local-small"
            # Không cho router fallback sang model cloud
            data["disable_fallbacks"] = True
            verbose_proxy_logger.info(
                "ben-governance label=%s model %s -> %s", label, original_model, data["model"]
            )
        return data
