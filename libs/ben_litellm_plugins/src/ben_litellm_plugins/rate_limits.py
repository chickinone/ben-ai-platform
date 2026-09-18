"""Giới hạn RPM/TPM dùng chung cho mọi LiteLLM worker.

LiteLLM vẫn nhận ``rpm_limit`` / ``tpm_limit`` trên team và virtual key để làm
nguồn policy và giới hạn mặc định. Hai worker của proxy, tuy nhiên, không được
phép mỗi worker có một quota độc lập. Module này dùng Redis làm bộ đếm nguyên tử
theo tenant và cửa sổ một phút để bảo đảm quota được chia sẻ giữa worker/pod.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

DEFAULT_MAX_TOKENS = 256
WINDOW_SECONDS = 60

_INCREMENT_WITH_EXPIRY = """
local current = redis.call('INCRBY', KEYS[1], ARGV[1])
if current == tonumber(ARGV[1]) then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return current
"""


class AsyncRedis(Protocol):
    # redis-py khai báo ``eval`` trả ``Awaitable[Any]``, không phải coroutine of int,
    # nên Protocol phải khớp đúng như vậy; ``consume_limit`` tự ép kiểu về int.
    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Awaitable[Any]: ...


@dataclass(frozen=True)
class TenantRatePolicy:
    """Policy đã lấy từ metadata tin cậy của virtual key."""

    tenant: str
    rpm: int
    tpm: int


def _positive_int(value: object, name: str) -> int:
    # ``bool`` là ``int`` trong Python nhưng không phải limit hợp lệ.
    if isinstance(value, bool):
        raise ValueError(f"{name} phải là số nguyên dương")
    try:
        number = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} phải là số nguyên dương") from exc
    if number <= 0:
        raise ValueError(f"{name} phải là số nguyên dương")
    return number


def policy_from_metadata(metadata: Mapping[str, Any] | None) -> TenantRatePolicy | None:
    """Đọc rate policy mà server đã gắn vào virtual key, không tin header client."""
    if not metadata:
        return None
    tenant = metadata.get("ben_tenant")
    if not isinstance(tenant, str) or not tenant.strip():
        return None
    rpm_value = metadata.get("ben_rpm_limit")
    tpm_value = metadata.get("ben_tpm_limit")
    # Key cũ chưa được seed lại không có guardrail chung; LiteLLM native vẫn là
    # fallback. Chỉ kích hoạt khi metadata policy đầy đủ, tránh đoán quota.
    if rpm_value is None or tpm_value is None:
        return None
    return TenantRatePolicy(
        tenant=tenant.strip(),
        rpm=_positive_int(rpm_value, "ben_rpm_limit"),
        tpm=_positive_int(tpm_value, "ben_tpm_limit"),
    )


def _tenant_hash(tenant: str) -> str:
    # Redis key không lộ slug tenant (dù slug demo vốn không nhạy cảm).
    return hashlib.sha256(tenant.encode("utf-8")).hexdigest()[:24]


def _counter_key(tenant: str, dimension: str, now: float) -> str:
    bucket = int(now // WINDOW_SECONDS)
    return f"ben:rate:{dimension}:{_tenant_hash(tenant)}:{bucket}"


def estimate_request_tokens(data: Mapping[str, Any]) -> int:
    """Ước lượng bảo thủ token cho quota TPM trước khi provider trả usage thật.

    Khi caller không truyền ``max_tokens``, dùng mức mặc định có chủ đích thay vì
    giả định bằng 0. Token prompt được ước lượng từ JSON canonical; LiteLLM vẫn
    giữ TPM native như lớp phòng vệ bổ sung sau khi có số token thực tế.
    """
    try:
        max_tokens = int(data.get("max_tokens") or DEFAULT_MAX_TOKENS)
    except (TypeError, ValueError):
        max_tokens = DEFAULT_MAX_TOKENS
    max_tokens = max(0, max_tokens)
    request_part = {
        name: data.get(name)
        for name in ("messages", "input", "prompt", "tools", "system")
        if data.get(name) is not None
    }
    serialized = json.dumps(request_part, ensure_ascii=False, sort_keys=True, default=str)
    prompt_tokens = max(1, (len(serialized) + 3) // 4)
    return prompt_tokens + max_tokens


async def consume_limit(client: AsyncRedis, key: str, amount: int, limit: int) -> bool:
    """Cộng nguyên tử vào quota fixed-window, trả về request còn được nhận hay không."""
    if amount <= 0 or limit <= 0:
        raise ValueError("amount và limit phải dương")
    observed = int(
        await client.eval(
            _INCREMENT_WITH_EXPIRY,
            1,
            key,
            str(amount),
            str(WINDOW_SECONDS + 1),
        )
    )
    return observed <= limit


async def consume_request(
    client: AsyncRedis,
    policy: TenantRatePolicy,
    data: Mapping[str, Any],
    *,
    now: float | None = None,
) -> tuple[Literal[True], None] | tuple[Literal[False], str]:
    """Nhận quota RPM rồi TPM; ``reason`` dùng cho phản hồi 429 không lộ key.

    Kiểu trả về nói rõ bất biến: đã từ chối thì luôn có ``reason``, nên caller
    không phải xử lý nhánh ``None`` không bao giờ xảy ra.
    """
    moment = time.time() if now is None else now
    rpm_ok = await consume_limit(
        client, _counter_key(policy.tenant, "rpm", moment), amount=1, limit=policy.rpm
    )
    if not rpm_ok:
        return False, "rpm"
    tpm_ok = await consume_limit(
        client,
        _counter_key(policy.tenant, "tpm", moment),
        amount=estimate_request_tokens(data),
        limit=policy.tpm,
    )
    return (True, None) if tpm_ok else (False, "tpm")
