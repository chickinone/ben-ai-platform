"""Đưa usage event từ Redis Streams vào Postgres theo mô hình at-least-once an toàn."""

from __future__ import annotations

import logging
import os
import socket
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import psycopg
import redis
from redis.exceptions import ResponseError

STREAM_KEY = "stream:usage"
GROUP = "metering"
DEAD_LETTER_STREAM = "stream:usage:dead-letter"
LOG = logging.getLogger(__name__)


class InvalidUsageEvent(ValueError):
    """Event không thể biến đổi thành usage record hợp lệ."""


@dataclass(frozen=True)
class UsageEvent:
    ts: datetime
    tenant_id: uuid.UUID
    endpoint: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    latency_ms: int
    cache_hit: bool
    trace_id: str


def _required(fields: Mapping[str, str], name: str) -> str:
    value = fields.get(name, "").strip()
    if not value:
        raise InvalidUsageEvent(f"Thiếu {name}")
    return value


def _integer(fields: Mapping[str, str], name: str) -> int:
    try:
        value = int(fields.get(name, "0"))
    except ValueError as exc:
        raise InvalidUsageEvent(f"{name} phải là số nguyên") from exc
    if value < 0:
        raise InvalidUsageEvent(f"{name} không được âm")
    return value


def _decimal(fields: Mapping[str, str], name: str) -> Decimal:
    try:
        value = Decimal(fields.get(name, "0"))
    except InvalidOperation as exc:
        raise InvalidUsageEvent(f"{name} phải là số") from exc
    if not value.is_finite() or value < 0:
        raise InvalidUsageEvent(f"{name} không hợp lệ")
    return value


def _boolean(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _timestamp(value: str) -> datetime:
    try:
        number = float(value)
    except ValueError as exc:
        raise InvalidUsageEvent("start_time không phải timestamp") from exc
    if number <= 0:
        raise InvalidUsageEvent("start_time không hợp lệ")
    return datetime.fromtimestamp(number, UTC)


def _latency_ms(fields: Mapping[str, str]) -> int:
    try:
        started = float(_required(fields, "start_time"))
        ended = float(_required(fields, "end_time"))
    except ValueError as exc:
        raise InvalidUsageEvent("timestamp không hợp lệ") from exc
    return max(0, round((ended - started) * 1000))


def _endpoint(call_type: str) -> str:
    return {
        "aembedding": "/v1/embeddings",
        "anthropic_messages": "/v1/messages",
    }.get(call_type, "/v1/chat/completions")


def parse_usage_event(fields: Mapping[str, str]) -> UsageEvent:
    try:
        tenant_id = uuid.UUID(_required(fields, "team_id"))
    except ValueError as exc:
        raise InvalidUsageEvent("team_id phải là UUID tenant") from exc
    return UsageEvent(
        ts=_timestamp(_required(fields, "end_time")),
        tenant_id=tenant_id,
        endpoint=_endpoint(fields.get("call_type", "")),
        model=_required(fields, "model"),
        tokens_in=_integer(fields, "tokens_in"),
        tokens_out=_integer(fields, "tokens_out"),
        cost_usd=_decimal(fields, "cost_usd"),
        latency_ms=_latency_ms(fields),
        cache_hit=_boolean(fields.get("cache_hit", "false")),
        # LiteLLM trace_id có thể trống trong mock; call_id vẫn là correlation ID đúng.
        trace_id=fields.get("trace_id") or _required(fields, "call_id"),
    )


class UsageConsumer:
    def __init__(self, redis_client: redis.Redis, database_url: str, consumer: str) -> None:
        self.redis = redis_client
        self.database_url = database_url
        self.consumer = consumer

    def ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(STREAM_KEY, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def _save(self, stream_id: str, event: UsageEvent) -> bool:
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cursor:
            # Receipt và usage row phải ở cùng transaction: sau crash trước XACK,
            # event được đọc lại nhưng receipt đã khiến lần sau no-op.
            cursor.execute(
                "INSERT INTO usage_event_receipts (stream_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (stream_id,),
            )
            if cursor.rowcount == 0:
                return False
            cursor.execute(
                """
                INSERT INTO usage_events (
                  ts, tenant_id, endpoint, model, tokens_in, tokens_out, cost_usd,
                  latency_ms, cache_hit, fallback, status, trace_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, false, 200, %s)
                """,
                (
                    event.ts,
                    event.tenant_id,
                    event.endpoint,
                    event.model,
                    event.tokens_in,
                    event.tokens_out,
                    event.cost_usd,
                    event.latency_ms,
                    event.cache_hit,
                    event.trace_id,
                ),
            )
            return True

    def _dead_letter(self, stream_id: str, fields: Mapping[str, str], reason: str) -> None:
        # redis-py khai báo field của xadd rộng hơn dict[str, str]; dict là invariant nên nới kiểu
        payload: dict[Any, Any] = {"source_stream_id": stream_id, "reason": reason, **fields}
        self.redis.xadd(DEAD_LETTER_STREAM, payload, maxlen=10_000, approximate=True)
        self.redis.xack(STREAM_KEY, GROUP, stream_id)

    def process(self, stream_id: str, fields: Mapping[str, str]) -> bool:
        try:
            event = parse_usage_event(fields)
        except InvalidUsageEvent as exc:
            LOG.warning("Usage event %s vào dead letter: %s", stream_id, exc)
            self._dead_letter(stream_id, fields, str(exc))
            return False
        inserted = self._save(stream_id, event)
        self.redis.xack(STREAM_KEY, GROUP, stream_id)
        return inserted

    def reclaim_pending(self) -> int:
        """Nhận lại event mồ côi sau 60 giây (ADR-005)."""
        next_id = "0-0"
        processed = 0
        while True:
            next_id, entries, _ = self.redis.xautoclaim(
                STREAM_KEY, GROUP, self.consumer, min_idle_time=60_000, start_id=next_id, count=100
            )
            for stream_id, fields in entries:
                self.process(stream_id, fields)
                processed += 1
            if next_id == "0-0" or not entries:
                return processed

    def run_forever(self) -> None:
        self.ensure_group()
        self.reclaim_pending()
        while True:
            # Stub của redis-py trả ``ResponseT`` chung chung; client đồng bộ với
            # decode_responses=True luôn trả về dạng [(stream, [(id, fields), ...])].
            records = cast(
                "list[tuple[str, list[tuple[str, Mapping[str, str]]]]]",
                self.redis.xreadgroup(
                    GROUP, self.consumer, {STREAM_KEY: ">"}, count=100, block=5_000
                ),
            )
            for _, entries in records:
                for stream_id, fields in entries:
                    self.process(stream_id, fields)


def main() -> None:
    logging.basicConfig(level=os.environ.get("BEN_LOG_LEVEL", "INFO"))
    redis_url = os.environ["BEN_REDIS_URL"]
    database_url = os.environ["BEN_METERING_DATABASE_URL"]
    consumer = os.environ.get("BEN_METERING_CONSUMER", f"{socket.gethostname()}-{os.getpid()}")
    # XREADGROUP chờ tối đa 5 giây; socket timeout phải lớn hơn khoảng chờ đó,
    # nếu không redis-py sẽ coi một lần chờ rỗng là lỗi kết nối.
    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
        health_check_interval=30,
    )
    try:
        UsageConsumer(client, database_url, consumer).run_forever()
    finally:
        client.close()


if __name__ == "__main__":
    main()
