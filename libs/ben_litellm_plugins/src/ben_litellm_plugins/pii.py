"""Che và khôi phục định danh cá nhân trong request/response LLM.

Bản tối thiểu cho tuần 3 (SĐT, CCCD). Bộ nhận diện đầy đủ ở tuần 5 (PROJECT.md §7.3).
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Recognizer:
    kind: str
    pattern: re.Pattern[str]


# Thứ tự quan trọng: CCCD (12 chữ số liền) chạy trước SĐT (10 chữ số)
DEFAULT_RECOGNIZERS: tuple[Recognizer, ...] = (
    Recognizer("CCCD", re.compile(r"(?<!\d)\d{12}(?!\d)")),
    Recognizer("PHONE", re.compile(r"(?<!\d)(?:\+84|0)(?:[\s.]?\d){9}(?!\d)")),
)

PLACEHOLDER_PATTERN = re.compile(r"<[A-Z]+_\d+>")
MAX_PLACEHOLDER_LENGTH = 16


class Redactor:
    """Thay định danh bằng placeholder ổn định trong phạm vi một request."""

    def __init__(self, recognizers: tuple[Recognizer, ...] = DEFAULT_RECOGNIZERS) -> None:
        self._recognizers = recognizers
        self.mapping: dict[str, str] = {}
        self._by_original: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def redact_text(self, text: str) -> str:
        for recognizer in self._recognizers:
            text = recognizer.pattern.sub(self._replacer(recognizer.kind), text)
        return text

    def _replacer(self, kind: str) -> Callable[[re.Match[str]], str]:
        def replace(match: re.Match[str]) -> str:
            return self._placeholder(kind, match.group(0))

        return replace

    def redact_content(self, content: Any) -> Any:
        """Nội dung dạng chuỗi, hoặc danh sách block có trường `text` (OpenAI và Anthropic)."""
        if isinstance(content, str):
            return self.redact_text(content)
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    part["text"] = self.redact_text(part["text"])
        return content

    def redact_request(self, data: dict) -> int:
        """Che messages và system prompt tại chỗ. Trả về số định danh khác nhau đã che."""
        for message in data.get("messages") or []:
            if isinstance(message, dict) and "content" in message:
                message["content"] = self.redact_content(message["content"])
        if "system" in data:
            data["system"] = self.redact_content(data["system"])
        return len(self.mapping)

    def _placeholder(self, kind: str, original: str) -> str:
        if original not in self._by_original:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            placeholder = f"<{kind}_{self._counters[kind]}>"
            self.mapping[placeholder] = original
            self._by_original[original] = placeholder
        return self._by_original[original]


def restore_text(text: str, mapping: Mapping[str, str]) -> str:
    if not mapping:
        return text
    return PLACEHOLDER_PATTERN.sub(lambda match: mapping.get(match.group(0), match.group(0)), text)


def restore_response(response: Any, mapping: Mapping[str, str]) -> Any:
    """Khôi phục tại chỗ trong response OpenAI (`choices`) hoặc Anthropic (`content` blocks)."""
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


def _get(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _set(obj: Any, name: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[name] = value
    else:
        setattr(obj, name, value)
