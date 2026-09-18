"""Tương thích plugin LiteLLM với package PII tiếng Việt của Week 5."""

from __future__ import annotations

from typing import Any

from ben_pii_vn.core import MAX_PLACEHOLDER_LENGTH, Redactor, mask_text, restore_text

__all__ = [
    "MAX_PLACEHOLDER_LENGTH",
    "Redactor",
    "mask_response",
    "restore_response",
    "restore_text",
]


def restore_response(response: Any, mapping: dict[str, str]) -> Any:
    """Khôi phục response OpenAI (choices) hoặc Anthropic (content blocks) tại chỗ."""
    if not mapping:
        return response
    choices = _get(response, "choices")
    if choices:
        for choice in choices:
            message = _get(choice, "message")
            content = _get(message, "content")
            if isinstance(content, str):
                _set(message, "content", restore_text(content, mapping))
        return response
    for block in _get(response, "content") or []:
        text = _get(block, "text")
        if isinstance(text, str):
            _set(block, "text", restore_text(text, mapping))
    return response


def mask_response(response: Any, exempt_values: set[str] | None = None) -> Any:
    """Mask PII mới trong output; giá trị vừa khôi phục có thể được miễn che theo policy."""
    exempt = exempt_values or set()
    choices = _get(response, "choices")
    if choices:
        for choice in choices:
            message = _get(choice, "message")
            content = _get(message, "content")
            if isinstance(content, str):
                _set(message, "content", mask_text(content, exempt))
        return response
    for block in _get(response, "content") or []:
        text = _get(block, "text")
        if isinstance(text, str):
            _set(block, "text", mask_text(text, exempt))
    return response


def _get(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _set(obj: Any, name: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[name] = value
    else:
        setattr(obj, name, value)
