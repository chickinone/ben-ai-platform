"""Policy PII lấy từ metadata virtual key do server cấp."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ben_pii_vn.core import PiiMode


@dataclass(frozen=True)
class PiiPolicy:
    mode: PiiMode = PiiMode.REDACT
    restore: bool = True


def policy_from_metadata(metadata: Mapping[str, Any] | None) -> PiiPolicy:
    """Thiếu/cấu hình sai policy luôn rơi về ``redact + restore`` an toàn, tương thích cũ."""
    raw_mode = metadata.get("ben_pii_mode") if metadata else None
    try:
        mode = PiiMode(str(raw_mode)) if raw_mode else PiiMode.REDACT
    except ValueError:
        mode = PiiMode.REDACT
    raw_restore = metadata.get("ben_pii_restore", True) if metadata else True
    restore = raw_restore if isinstance(raw_restore, bool) else str(raw_restore).lower() == "true"
    return PiiPolicy(mode=mode, restore=restore if mode is PiiMode.REDACT else False)
