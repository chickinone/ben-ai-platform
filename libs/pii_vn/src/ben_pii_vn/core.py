"""Nhận diện PII tiếng Việt theo luật dễ kiểm chứng, không gửi dữ liệu sang dịch vụ ngoài."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PiiMode(StrEnum):
    REDACT = "redact"
    MASK = "mask"
    BLOCK = "block"
    OFF = "off"


@dataclass(frozen=True)
class PiiEntity:
    kind: str
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class Recognizer:
    kind: str
    pattern: re.Pattern[str]
    value_group: int | str | None = None
    validator: Callable[[str], bool] | None = None


def _valid_cccd(value: str) -> bool:
    """CCCD có 12 số; ba số đầu thuộc dải mã tỉnh lịch sử 001–096."""
    return len(value) == 12 and 1 <= int(value[:3]) <= 96


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _valid_bank_account(value: str) -> bool:
    return 8 <= len(_digits(value)) <= 19


# Priority cao hơn chạy trước khi span chồng nhau: CCCD là dãy số dài cũng có thể
# xuất hiện cạnh từ khoá tài khoản. Họ tên chỉ nhận diện khi có ngữ cảnh để giảm FP.
DEFAULT_RECOGNIZERS: tuple[Recognizer, ...] = (
    Recognizer("CCCD", re.compile(r"(?<!\d)(\d{12})(?!\d)"), 1, _valid_cccd),
    Recognizer(
        "PHONE",
        re.compile(r"(?<!\d)((?:\+84|0)[\s.]?[35789](?:[\s.]?\d){8})(?!\d)"),
        1,
    ),
    Recognizer(
        "EMAIL",
        re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])", re.I),
        1,
    ),
    Recognizer(
        "BANK",
        re.compile(
            r"(?i)\b(?:stk|số\s*tài\s*khoản|tài\s*khoản|ngân\s*hàng)\s*(?:là|:)?\s*"
            r"(?P<value>\d(?:[\s.-]?\d){7,18})"
        ),
        "value",
        _valid_bank_account,
    ),
    Recognizer("ORDER", re.compile(r"(?<!\w)(#[A-Z][A-Z0-9]{3,})(?!\w)", re.I), 1),
    Recognizer(
        "NAME",
        re.compile(
            r"(?i)\b(?:họ\s*(?:và\s*)?tên|khách\s*hàng|người\s*nhận|tên)\s*[:\-]?\s*"
            r"(?P<value>(?:nguyễn|trần|lê|phạm|hoàng|huỳnh|phan|vũ|võ|đặng|bùi|đỗ|hồ|ngô|"
            r"dương|lý)\s+(?:[a-zà-ỹđ]+\s*){1,4})"
        ),
        "value",
    ),
)

PLACEHOLDER_PATTERN = re.compile(r"<[A-Z]+_\d+>")
MAX_PLACEHOLDER_LENGTH = 16


def detect_pii(
    text: str, recognizers: Iterable[Recognizer] = DEFAULT_RECOGNIZERS
) -> list[PiiEntity]:
    """Trả entity không chồng nhau, theo thứ tự xuất hiện trong chuỗi."""
    candidates: list[tuple[int, int, int, PiiEntity]] = []
    for priority, recognizer in enumerate(recognizers):
        for match in recognizer.pattern.finditer(text):
            if recognizer.value_group:
                value = match.group(recognizer.value_group)
                start, end = match.span(recognizer.value_group)
            else:
                value = match.group(0)
                start, end = match.span(0)
            if recognizer.validator is not None and not recognizer.validator(value):
                continue
            candidates.append((start, end, priority, PiiEntity(recognizer.kind, value, start, end)))

    result: list[PiiEntity] = []
    occupied_until = -1
    for start, end, _priority, entity in sorted(
        candidates, key=lambda item: (item[0], item[2], item[1])
    ):
        if start >= occupied_until:
            result.append(entity)
            occupied_until = end
    return result


class Redactor:
    """Thay PII bằng placeholder ổn định trong phạm vi một request."""

    def __init__(self, recognizers: tuple[Recognizer, ...] = DEFAULT_RECOGNIZERS) -> None:
        self._recognizers = recognizers
        self.mapping: dict[str, str] = {}
        self._by_original: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = {}

    def redact_text(self, text: str) -> str:
        entities = detect_pii(text, self._recognizers)
        if not entities:
            return text
        parts: list[str] = []
        cursor = 0
        for entity in entities:
            parts.extend(
                (text[cursor : entity.start], self._placeholder(entity.kind, entity.value))
            )
            cursor = entity.end
        parts.append(text[cursor:])
        return "".join(parts)

    def redact_content(self, content: Any) -> Any:
        """Che nội dung kiểu OpenAI/Anthropic mà không sửa metadata protocol."""
        if isinstance(content, str):
            return self.redact_text(content)
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    part["text"] = self.redact_text(part["text"])
        return content

    def redact_request(self, data: dict[str, Any]) -> int:
        for message in data.get("messages") or []:
            if isinstance(message, dict) and "content" in message:
                message["content"] = self.redact_content(message["content"])
        for field in ("system", "input", "prompt"):
            if field in data:
                data[field] = self.redact_content(data[field])
        return len(self.mapping)

    def _placeholder(self, kind: str, original: str) -> str:
        key = (kind, original)
        if key not in self._by_original:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            placeholder = f"<{kind}_{self._counters[kind]}>"
            self.mapping[placeholder] = original
            self._by_original[key] = placeholder
        return self._by_original[key]


def restore_text(text: str, mapping: Mapping[str, str]) -> str:
    return PLACEHOLDER_PATTERN.sub(lambda match: mapping.get(match.group(0), match.group(0)), text)


def _masked_value(entity: PiiEntity) -> str:
    if entity.kind == "EMAIL":
        local, _, domain = entity.value.partition("@")
        return f"{local[:1]}***@{domain}" if domain else "***"
    if entity.kind in {"PHONE", "CCCD", "BANK"}:
        digits = _digits(entity.value)
        return f"***{digits[-3:]}" if len(digits) >= 3 else "***"
    if entity.kind == "ORDER":
        return "#***"
    return "[ĐÃ CHE]"


def mask_text(text: str, exempt_values: Iterable[str] = ()) -> str:
    """Mask không đảo ngược, dùng cho output PII mới hoặc policy ``mask``."""
    entities = detect_pii(text)
    if not entities:
        return text
    parts: list[str] = []
    cursor = 0
    exempt = frozenset(exempt_values)
    for entity in entities:
        replacement = entity.value if entity.value in exempt else _masked_value(entity)
        parts.extend((text[cursor : entity.start], replacement))
        cursor = entity.end
    parts.append(text[cursor:])
    return "".join(parts)
