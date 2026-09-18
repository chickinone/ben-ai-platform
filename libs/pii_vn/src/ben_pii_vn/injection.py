"""Heuristic injection có thể giải thích được; không thay thế classifier ở giai đoạn sau."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionFinding:
    rule: str
    evidence: str


RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(
            r"(?i)\b(?:ignore|disregard|bỏ\s*qua)\b.{0,50}\b(?:previous|prior|hướng\s*dẫn|chỉ\s*dẫn)\b"
        ),
    ),
    (
        "reveal_system_prompt",
        re.compile(
            r"(?i)\b(?:reveal|show|print|tiết\s*lộ|hiển\s*thị)\b.{0,50}\b(?:system\s*prompt|prompt\s*hệ\s*thống|instructions)\b"
        ),
    ),
    (
        "role_override",
        re.compile(r"(?i)\b(?:you\s+are\s+now|act\s+as|từ\s*giờ\s*bạn\s*là|đóng\s*vai)\b"),
    ),
    ("delimiter_escape", re.compile(r"(?i)(?:<\/?system>|```system|\[\[system\]\])")),
)


def detect_prompt_injection(text: str) -> list[InjectionFinding]:
    findings: list[InjectionFinding] = []
    for name, pattern in RULES:
        match = pattern.search(text)
        if match:
            findings.append(InjectionFinding(name, match.group(0)[:160]))
    return findings
