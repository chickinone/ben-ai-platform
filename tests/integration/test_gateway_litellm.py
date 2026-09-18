"""Tuần 3 — "Xong khi": SDK openai/anthropic qua virtual key của tenant, ngân sách chặn được,
PII khôi phục đúng khi proxy chạy 2 worker, nhãn chỉ tin từ key dịch vụ, metering theo tenant.
"""

import os
import time
import uuid

import anthropic
import httpx
import openai
import pytest

PROXY_URL = os.environ.get("BEN_PROXY_URL", "http://127.0.0.1:4000")

PHONE = "0912 345 678"


def unique(text: str) -> str:
    return f"[{uuid.uuid4().hex[:8]}] {text}"


def contains_phone(value: str) -> bool:
    return PHONE in value or PHONE.replace(" ", "") in value


def openai_client(key: str) -> openai.OpenAI:
    # Client mới cho mỗi lần gọi → kết nối mới → có cơ hội rơi vào worker khác
    return openai.OpenAI(base_url=f"{PROXY_URL}/v1", api_key=key, max_retries=0)


def anthropic_client(key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(base_url=PROXY_URL, api_key=key, max_retries=0)


def ask(key: str, model: str, text: str, **kwargs):
    return openai_client(key).chat.completions.create(
        model=model, messages=[{"role": "user", "content": text}], **kwargs
    )


def test_openai_sdk_works_with_tenant_virtual_key(tenant, mock_cloud):
    t = tenant(models=["mock-cloud-small"])
    completion = ask(t["key"], "mock-cloud-small", unique("Chính sách đổi trả bao lâu?"))

    assert completion.choices[0].message.content.startswith("[cloud]")
    assert len(mock_cloud.requests()) == 1


def test_virtual_key_enforces_tenant_rpm_policy(tenant):
    """LiteLLM cần limit nằm ở key để thực thi chắc chắn với virtual key."""
    t = tenant(models=["mock-cloud-small"], rpm_limit=1, tpm_limit=1_000)
    ask(t["key"], "mock-cloud-small", unique("Lần gọi thứ nhất"))

    with pytest.raises(openai.RateLimitError):
        ask(t["key"], "mock-cloud-small", unique("Lần gọi thứ hai"))


def test_anthropic_sdk_v1_messages_redacts_and_restores(tenant, mock_cloud):
    t = tenant(models=["mock-claude"])
    message = anthropic_client(t["key"]).messages.create(
        model="mock-claude",
        max_tokens=256,
        messages=[{"role": "user", "content": unique(f"SĐT {PHONE}, kiểm tra đơn giúp")}],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    sent = mock_cloud.sent_text()

    assert "<PHONE_1>" in sent and not contains_phone(sent)
    assert contains_phone(text)


def test_anthropic_sdk_v1_messages_stream_redacts_and_restores(tenant, mock_cloud):
    """SSE Anthropic phải khôi phục placeholder, kể cả khi mock cắt giữa ``<PHONE_1>``."""
    t = tenant(models=["mock-claude"])
    stream = anthropic_client(t["key"]).messages.create(
        model="mock-claude",
        max_tokens=256,
        stream=True,
        messages=[{"role": "user", "content": unique(f"SĐT {PHONE}, kiểm tra đơn giúp")}],
    )
    text = "".join(
        event.delta.text
        for event in stream
        if event.type == "content_block_delta" and getattr(event.delta, "text", None)
    )

    assert "<PHONE_1>" in mock_cloud.sent_text() and not contains_phone(mock_cloud.sent_text())
    assert contains_phone(text)


def test_anthropic_passthrough_is_not_publicly_routable(tenant, mock_cloud):
    """Không sửa passthrough một chiều; edge phải chặn nó trước khi tới LiteLLM/provider."""
    t = tenant(models=["mock-claude"])
    response = httpx.post(
        f"{PROXY_URL}/anthropic/v1/messages",
        headers={"Authorization": f"Bearer {t['key']}", "anthropic-version": "2023-06-01"},
        json={
            "model": "mock-claude",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": unique(f"SĐT {PHONE}")}],
        },
        timeout=10,
    )

    assert response.status_code == 404
    assert mock_cloud.requests() == []


def test_key_cannot_call_model_outside_its_allowlist(tenant, mock_local):
    t = tenant(models=["mock-cloud-small"])
    with pytest.raises(openai.APIStatusError) as exc_info:
        ask(t["key"], "mock-local-small", unique("Xin chào"))

    assert exc_info.value.status_code in (401, 403)
    assert mock_local.requests() == []


def test_budget_exceeded_blocks_tenant_key(tenant, admin, findings):
    budget_usd = 0.0002  # mỗi lần gọi mock-cloud-small tốn ~8e-5 USD
    t = tenant(models=["mock-cloud-small"], max_budget=budget_usd)

    successes = 0
    blocked: openai.APIStatusError | None = None
    for _ in range(20):
        try:
            ask(t["key"], "mock-cloud-small", unique("Phí giao hàng nội thành?"))
            successes += 1
        except openai.APIStatusError as exc:
            blocked = exc
            break
        time.sleep(0.5)

    key_info = admin.get("/key/info", params={"key": t["key"]}).json().get("info", {})
    findings["budget"] = {
        "max_budget_usd": budget_usd,
        "successful_calls_before_block": successes,
        "spend_recorded_usd": key_info.get("spend"),
        "block_status": blocked.status_code if blocked else None,
        "block_message": str(blocked)[:300] if blocked else None,
    }

    assert blocked is not None, "Key vẫn gọi được sau 20 lần dù vượt ngân sách"
    assert "budget" in str(blocked).lower()


def test_pii_restored_consistently_across_workers(tenant, mock_cloud, pii_store_redis, findings):
    t = tenant(models=["mock-cloud-small"])
    failures: list[tuple[int, str]] = []

    for i in range(20):
        prompt = unique(f"Lần {i}: gọi lại cho tôi số {PHONE}")
        if i % 2 == 0:
            text = ask(t["key"], "mock-cloud-small", prompt).choices[0].message.content
        else:
            stream = ask(t["key"], "mock-cloud-small", prompt, stream=True)
            text = "".join(
                chunk.choices[0].delta.content or ""
                for chunk in stream
                if chunk.choices and chunk.choices[0].delta
            )
        if not contains_phone(text) or "PHONE" in text:
            failures.append((i, text))

    mapping_keys = list(pii_store_redis.scan_iter("ben:pii-map:*"))
    stored = b"".join(pii_store_redis.get(k) or b"" for k in mapping_keys)
    findings["multi_worker_pii"] = {
        "requests": 20,
        "failures": failures,
        "mapping_keys_in_redis": len(mapping_keys),
    }

    assert failures == []
    assert not contains_phone(mock_cloud.sent_text())
    assert mapping_keys, "Không thấy kho ánh xạ trên Redis — plugin có dùng RedisMappingStore?"
    assert b"0912" not in stored, "Kho ánh xạ trên Redis chứa SĐT dạng rõ"


def test_label_header_from_regular_key_is_ignored(tenant, mock_local):
    t = tenant(models=["mock-cloud-small", "mock-local-small"])
    completion = ask(
        t["key"],
        "mock-cloud-small",
        unique("Kế hoạch giá Q4"),
        extra_headers={"x-ben-context-label": "confidential"},
    )

    assert completion.choices[0].message.content.startswith("[cloud]")
    assert mock_local.requests() == []


def test_service_key_label_forces_local_and_blocks_fallback_to_cloud(
    tenant, mock_cloud, mock_local
):
    t = tenant(models=["mock-cloud-small", "mock-local-small"], service=True)
    label = {"x-ben-context-label": "confidential"}

    completion = ask(t["key"], "mock-cloud-small", unique("Kế hoạch giá Q4"), extra_headers=label)
    assert completion.choices[0].message.content.startswith("[local]")

    mock_local.fail(True)
    with pytest.raises(openai.APIStatusError):
        ask(t["key"], "mock-cloud-small", unique("Doanh thu Q3"), extra_headers=label)

    assert mock_cloud.requests() == [], "Dữ liệu Confidential đã tới model cloud"


def test_usage_event_is_attributed_to_tenant(tenant, usage_stream, findings):
    t = tenant(models=["mock-cloud-small"])
    raw = openai_client(t["key"]).chat.completions.with_raw_response.create(
        model="mock-cloud-small",
        messages=[{"role": "user", "content": unique("Giờ làm việc tổng đài?")}],
    )
    completion = raw.parse()
    call_id = raw.headers.get("x-litellm-call-id", "")

    event: dict = {}
    deadline = time.monotonic() + 15
    while not event and time.monotonic() < deadline:
        for _, fields in usage_stream.xrevrange("stream:usage", count=500):
            if fields.get("call_id") == call_id:
                event = fields
                break
        time.sleep(0.3)
    findings["usage_event"] = event

    assert event, f"Không thấy usage event cho {call_id}"
    assert event["team_id"] == t["team_id"]
    assert int(event["tokens_in"]) == completion.usage.prompt_tokens
    assert int(event["tokens_out"]) == completion.usage.completion_tokens
    expected = completion.usage.prompt_tokens * 1e-6 + completion.usage.completion_tokens * 5e-6
    assert float(event["cost_usd"]) == pytest.approx(expected, rel=0.01)
