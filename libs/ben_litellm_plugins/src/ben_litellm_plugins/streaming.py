"""Khôi phục placeholder trong response streaming, kể cả khi bị cắt qua nhiều chunk."""

import json
from collections.abc import Mapping
from typing import Any

from ben_litellm_plugins.pii import MAX_PLACEHOLDER_LENGTH, restore_text


def split_safe(buffer: str) -> tuple[str, str]:
    """Tách phần đã an toàn để gửi và phần đuôi có thể là placeholder chưa trọn (ví dụ '<PHO')."""
    index = buffer.rfind("<")
    if index != -1 and ">" not in buffer[index:] and len(buffer) - index < MAX_PLACEHOLDER_LENGTH:
        return buffer[:index], buffer[index:]
    return buffer, ""


class StreamRestorer:
    def __init__(self, mapping: Mapping[str, str]) -> None:
        self._mapping = mapping
        self._pending = ""

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    def feed(self, text: str) -> str:
        safe, self._pending = split_safe(self._pending + text)
        return restore_text(safe, self._mapping)

    def flush(self) -> str:
        text, self._pending = self._pending, ""
        return restore_text(text, self._mapping)


def restore_anthropic_sse_chunk(chunk: str | bytes, restorer: StreamRestorer) -> str | bytes:
    """Khôi phục text trong một raw Anthropic SSE frame LiteLLM đưa vào guardrail.

    ``/v1/messages`` streaming không đưa ``ModelResponse`` chunk vào hook mà đưa raw
    SSE (str/bytes). Ta chỉ sửa JSON của ``content_block_delta`` và giữ nguyên các
    event/field khác để SDK Anthropic tiếp tục nhận đúng wire protocol.
    """
    if isinstance(chunk, bytes):
        is_bytes = True
        try:
            source = chunk.decode("utf-8")
        except UnicodeDecodeError:
            return chunk
    else:
        is_bytes = False
        source = chunk

    lines: list[str] = []
    for line in source.splitlines(keepends=True):
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        content = line[: -len(ending)] if ending else line
        if not content.startswith("data: "):
            lines.append(line)
            continue
        try:
            payload: Any = json.loads(content.removeprefix("data: "))
        except json.JSONDecodeError:
            lines.append(line)
            continue
        if not isinstance(payload, dict):
            lines.append(line)
            continue
        delta = payload.get("delta")
        if not isinstance(delta, dict):
            lines.append(line)
            continue
        text = delta.get("text")
        if not isinstance(text, str):
            lines.append(line)
            continue
        delta["text"] = restorer.feed(text)
        lines.append(
            f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}{ending}"
        )

    result = "".join(lines)
    return result.encode("utf-8") if is_bytes else result
