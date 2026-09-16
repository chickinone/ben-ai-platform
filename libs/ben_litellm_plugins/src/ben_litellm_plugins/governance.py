"""Định tuyến theo nhãn dữ liệu — giả lập quyết định OPA cho đến tuần 11.

Ranh giới tin cậy (threat model B2): nhãn context chỉ được tin khi request đến từ dịch vụ
nội bộ, nhận biết qua metadata của virtual key `ben_service: true`. Header nhãn do app
tenant tự gửi bị bỏ qua.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

LABEL_HEADER = "x-ben-context-label"
SERVICE_KEY_FLAG = "ben_service"
LOCAL_ONLY_LABELS = frozenset({"confidential", "restricted"})


@dataclass(frozen=True)
class RoutingDecision:
    model: str
    disable_fallbacks: bool
    reason: str | None = None


def normalize_headers(data: Mapping[str, Any]) -> dict[str, str]:
    """Header request có thể nằm ở vài chỗ trong `data` tuỳ route của LiteLLM."""
    candidates = (
        (data.get("proxy_server_request") or {}).get("headers"),
        data.get("headers"),
        (data.get("metadata") or {}).get("headers"),
        (data.get("litellm_metadata") or {}).get("headers"),
    )
    merged: dict[str, str] = {}
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            merged.update({str(k).lower(): str(v) for k, v in candidate.items()})
    return merged


def trusted_label(headers: Mapping[str, str], key_metadata: Mapping[str, Any] | None) -> str | None:
    if not key_metadata or key_metadata.get(SERVICE_KEY_FLAG) is not True:
        return None
    label = headers.get(LABEL_HEADER)
    return label.strip().lower() if label else None


def decide_routing(
    requested_model: str,
    label: str | None,
    local_models: Collection[str],
    default_local_model: str,
) -> RoutingDecision:
    if label not in LOCAL_ONLY_LABELS:
        return RoutingDecision(model=requested_model, disable_fallbacks=False)
    model = requested_model if requested_model in local_models else default_local_model
    # TODO(tuần 11): Restricted phải bị từ chối hoặc che hoàn toàn, không chỉ ép local
    return RoutingDecision(model=model, disable_fallbacks=True, reason=f"label={label}")
