"""Khôi phục placeholder trong response streaming, kể cả khi bị cắt qua nhiều chunk."""

from collections.abc import Mapping

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
