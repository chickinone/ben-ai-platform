"""Consumer immutable audit event phát từ guardrail (không chứa prompt/PII thô)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import psycopg
import redis
from redis.exceptions import ResponseError

STREAM_KEY = "stream:guardrail"
GROUP = "guardrail-audit"
DEAD_LETTER_STREAM = "stream:guardrail:dead-letter"


class InvalidAuditEvent(ValueError):
    """Audit event thiếu dữ liệu cấu trúc hoặc cố đưa payload không hợp lệ."""


@dataclass(frozen=True)
class AuditEvent:
    ts: datetime
    actor: str
    action: str
    resource: str
    detail: dict[str, Any]


def _required(fields: Mapping[str, str], name: str) -> str:
    value = fields.get(name, "").strip()
    if not value:
        raise InvalidAuditEvent(f"Thiếu {name}")
    return value


def _contains_request_content(value: Any) -> bool:
    """Không để prompt ẩn dưới nested JSON trong audit detail."""
    if isinstance(value, dict):
        return any(
            str(key).lower() in {"prompt", "content", "text", "evidence"}
            or _contains_request_content(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_request_content(child) for child in value)
    return False


def parse_audit_event(fields: Mapping[str, str]) -> AuditEvent:
    try:
        ts = datetime.fromtimestamp(float(_required(fields, "ts")), UTC)
    except ValueError as exc:
        raise InvalidAuditEvent("ts không hợp lệ") from exc
    try:
        detail = json.loads(_required(fields, "detail"))
    except json.JSONDecodeError as exc:
        raise InvalidAuditEvent("detail không phải JSON") from exc
    if not isinstance(detail, dict):
        raise InvalidAuditEvent("detail phải là JSON object")
    # Hàng rào chống vô tình biến stream audit thành nơi lưu nội dung request.
    if _contains_request_content(detail):
        raise InvalidAuditEvent("detail không được chứa nội dung request")
    return AuditEvent(
        ts=ts,
        actor=_required(fields, "actor"),
        action=_required(fields, "action"),
        resource=_required(fields, "resource"),
        detail=detail,
    )


class AuditConsumer:
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

    def _save(self, stream_id: str, event: AuditEvent) -> bool:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                (
                    "INSERT INTO guardrail_audit_receipts (stream_id) "
                    "VALUES (%s) ON CONFLICT DO NOTHING"
                ),
                (stream_id,),
            )
            if cursor.rowcount == 0:
                return False
            cursor.execute(
                """
                INSERT INTO audit_logs (ts, actor, action, resource, detail)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (event.ts, event.actor, event.action, event.resource, json.dumps(event.detail)),
            )
            return True

    def process(self, stream_id: str, fields: Mapping[str, str]) -> bool:
        try:
            event = parse_audit_event(fields)
        except InvalidAuditEvent as exc:
            payload: dict[Any, Any] = {"source_stream_id": stream_id, "reason": str(exc), **fields}
            self.redis.xadd(DEAD_LETTER_STREAM, payload, maxlen=10_000, approximate=True)
            self.redis.xack(STREAM_KEY, GROUP, stream_id)
            return False
        inserted = self._save(stream_id, event)
        self.redis.xack(STREAM_KEY, GROUP, stream_id)
        return inserted

    def reclaim_pending(self) -> int:
        """Nhận lại audit event mồ côi sau 60 giây, cùng semantics usage stream."""
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
            records = cast(
                "list[tuple[str, list[tuple[str, Mapping[str, str]]]]]",
                self.redis.xreadgroup(
                    GROUP, self.consumer, {STREAM_KEY: ">"}, count=100, block=5_000
                ),
            )
            for _, entries in records:
                for stream_id, fields in entries:
                    self.process(stream_id, fields)
