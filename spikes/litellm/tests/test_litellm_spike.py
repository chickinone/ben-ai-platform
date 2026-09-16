"""Sáu kiểm tra quyết định có dùng LiteLLM Proxy làm lõi gateway của Bến hay không.

Mỗi test tương ứng một rủi ro đã nêu khi xem lại ADR-001.
Kết quả chi tiết (kể cả quan sát không phải điều kiện pass/fail) ghi vào results/findings.json.
"""

import json
import time
import uuid

import openai
import pytest

PHONE = "0912 345 678"
PHONE_VARIANTS = (PHONE, PHONE.replace(" ", ""))


def unique_prompt(text: str) -> str:
    return f"[{uuid.uuid4().hex[:8]}] {text}"


def contains_raw_phone(value: str) -> bool:
    return any(variant in value for variant in PHONE_VARIANTS)


def dump_redis(client) -> str:
    parts: list[str] = []
    for key in client.scan_iter(count=500):
        parts.append(key)
        kind = client.type(key)
        if kind == "string":
            parts.append(str(client.get(key)))
        elif kind == "hash":
            parts.append(json.dumps(client.hgetall(key), ensure_ascii=False))
        elif kind == "list":
            parts.extend(client.lrange(key, 0, -1))
        elif kind == "set":
            parts.extend(client.smembers(key))
        elif kind == "zset":
            parts.extend(client.zrange(key, 0, -1))
        elif kind == "stream":
            parts.append(json.dumps(client.xrange(key), ensure_ascii=False))
    return "\n".join(parts)


def wait_usage_event(redis_client, call_id: str, timeout_s: float = 10) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for _, fields in redis_client.xrange("stream:ben-usage-spike"):
            if call_id in (fields.get("call_id"), fields.get("slo_id")):
                return fields
        time.sleep(0.2)
    return {}


# ---------------------------------------------------------------------------
# 1. Thứ tự so với cache & logging: không nơi lưu nào giữ SĐT thô
# ---------------------------------------------------------------------------
def test_1_cache_and_logs_never_store_raw_pii(
    openai_client, redis_client, mock_cloud, proxy_logs, findings
):
    prompt = unique_prompt(f"Khách hỏi: SĐT {PHONE} sao chưa giao đơn?")
    messages = [{"role": "user", "content": prompt}]

    first = openai_client.chat.completions.with_raw_response.create(
        model="cloud-small", messages=messages
    )
    second = openai_client.chat.completions.with_raw_response.create(
        model="cloud-small", messages=messages
    )
    first_text = first.parse().choices[0].message.content
    second_text = second.parse().choices[0].message.content
    time.sleep(1.5)  # chờ callback logging bất đồng bộ

    events = [f for _, f in redis_client.xrange("stream:ben-usage-spike")]
    redis_dump = dump_redis(redis_client)
    logs = proxy_logs()
    findings["1_cache_and_logs"] = {
        "provider_calls": len(mock_cloud.requests()),
        "second_call_cache_key_header": second.headers.get("x-litellm-cache-key"),
        "first_response_restored": contains_raw_phone(first_text),
        "second_response_restored": contains_raw_phone(second_text),
        "raw_phone_in_redis": contains_raw_phone(redis_dump),
        "raw_phone_in_proxy_logs": contains_raw_phone(logs),
        "logging_payload_raw_phone_in_messages": [e.get("raw_phone_in_messages") for e in events],
        "logging_payload_raw_phone_in_response": [e.get("raw_phone_in_response") for e in events],
    }

    assert contains_raw_phone(first_text), "Lần gọi đầu không khôi phục SĐT"
    assert contains_raw_phone(second_text), "Lần gọi thứ hai (có thể cache hit) không khôi phục SĐT"
    assert not contains_raw_phone(redis_dump), "Redis (cache) chứa SĐT thô"
    assert not contains_raw_phone(logs), "Log của proxy chứa SĐT thô"
    assert events, "Callback logging không nhận event nào"
    assert all(e.get("raw_phone_in_messages") == "False" for e in events), (
        "Payload logging (thứ Langfuse nhận) chứa SĐT thô trong messages"
    )
    assert all(e.get("raw_phone_in_response") == "False" for e in events), (
        "Payload logging (thứ Langfuse nhận) chứa SĐT thô trong response đã khôi phục"
    )


# ---------------------------------------------------------------------------
# 2. Che PII có đảo ngược, cả response thường và streaming
# ---------------------------------------------------------------------------
def test_2a_pii_redacted_for_provider_and_restored_for_client(openai_client, mock_cloud, findings):
    prompt = unique_prompt(f"SĐT của tôi là {PHONE}, hãy xác nhận lại")
    completion = openai_client.chat.completions.create(
        model="cloud-small", messages=[{"role": "user", "content": prompt}]
    )
    text = completion.choices[0].message.content
    sent = "".join(r["raw"] for r in mock_cloud.requests())
    findings["2a_non_stream"] = {
        "provider_saw_raw_phone": contains_raw_phone(sent),
        "provider_saw_placeholder": "<PHONE_1>" in sent,
        "client_got_restored": contains_raw_phone(text),
    }

    assert sent, "Mock cloud không nhận request nào"
    assert not contains_raw_phone(sent), "Provider nhận SĐT thô"
    assert "<PHONE_1>" in sent
    assert contains_raw_phone(text) and "<PHONE_" not in text


def test_2b_streaming_restores_placeholder_split_across_chunks(openai_client, mock_cloud, findings):
    prompt = unique_prompt(f"Gọi lại cho tôi số {PHONE} nhé")
    stream = openai_client.chat.completions.create(
        model="cloud-small", messages=[{"role": "user", "content": prompt}], stream=True
    )
    text = "".join(
        chunk.choices[0].delta.content or ""
        for chunk in stream
        if chunk.choices and chunk.choices[0].delta
    )
    sent = "".join(r["raw"] for r in mock_cloud.requests())
    findings["2b_stream"] = {
        "provider_saw_raw_phone": contains_raw_phone(sent),
        "client_text": text,
    }

    assert not contains_raw_phone(sent), "Provider nhận SĐT thô (streaming)"
    assert contains_raw_phone(text), "Client không nhận SĐT đã khôi phục khi streaming"
    assert "<PHONE_" not in text and "PHONE_" not in text, "Placeholder lọt ra client"


# ---------------------------------------------------------------------------
# 3. Định tuyến theo nhãn và fallback không làm rò rỉ sang cloud
# ---------------------------------------------------------------------------
def test_3a_confidential_label_reroutes_to_local(openai_client, mock_cloud, mock_local, findings):
    completion = openai_client.chat.completions.create(
        model="cloud-small",
        messages=[{"role": "user", "content": unique_prompt("Tóm tắt kế hoạch giá Q4")}],
        extra_headers={"x-ben-context-label": "confidential"},
    )
    text = completion.choices[0].message.content
    findings["3a_reroute"] = {
        "cloud_calls": len(mock_cloud.requests()),
        "local_calls": len(mock_local.requests()),
        "answered_by": text[:10],
    }

    assert mock_cloud.requests() == [], "Request Confidential vẫn tới model cloud"
    assert len(mock_local.requests()) == 1
    assert text.startswith("[local]")


def test_3b_fallback_never_sends_confidential_to_cloud(
    openai_client, mock_cloud, mock_local, findings
):
    mock_local.fail(True)
    error: str | None = None
    try:
        openai_client.chat.completions.create(
            model="cloud-small",
            messages=[{"role": "user", "content": unique_prompt("Doanh thu chi tiết Q3")}],
            extra_headers={"x-ben-context-label": "confidential"},
        )
    except openai.APIStatusError as exc:
        error = f"{exc.status_code}"
    findings["3b_fallback_leak"] = {
        "cloud_calls": len(mock_cloud.requests()),
        "local_calls": len(mock_local.requests()),
        "client_error_status": error,
    }

    assert mock_cloud.requests() == [], "Fallback đã gửi dữ liệu Confidential sang cloud"
    assert error is not None, "Model local lỗi nhưng client vẫn nhận câu trả lời thành công"


def test_3c_sanity_fallback_works_without_label(openai_client, mock_cloud, mock_local, findings):
    mock_cloud.fail(True)
    completion = openai_client.chat.completions.create(
        model="cloud-small",
        messages=[{"role": "user", "content": unique_prompt("Chính sách đổi trả bao lâu?")}],
    )
    text = completion.choices[0].message.content
    findings["3c_fallback_sanity"] = {"answered_by": text[:10]}

    assert text.startswith("[local]"), "Fallback cấu hình sẵn không hoạt động — test 3b vô nghĩa"


# ---------------------------------------------------------------------------
# 4. Endpoint Anthropic: /v1/messages hợp nhất và passthrough /anthropic
# ---------------------------------------------------------------------------
def _anthropic_sent(mock_cloud) -> str:
    return "".join(r["raw"] for r in mock_cloud.requests() if r["path"] == "/v1/messages")


def test_4a_unified_v1_messages_runs_pii_guardrail(anthropic_unified_client, mock_cloud, findings):
    message = anthropic_unified_client.messages.create(
        model="claude-mock",
        max_tokens=256,
        messages=[{"role": "user", "content": unique_prompt(f"SĐT {PHONE}, kiểm tra đơn giúp")}],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    sent = _anthropic_sent(mock_cloud)
    findings["4a_unified_messages"] = {
        "provider_saw_raw_phone": contains_raw_phone(sent),
        "client_got_restored": contains_raw_phone(text),
    }

    assert sent, "Mock không nhận request Anthropic"
    assert not contains_raw_phone(sent), "/v1/messages: provider nhận SĐT thô"
    assert "<PHONE_1>" in sent, "/v1/messages: không thấy placeholder — guardrail có thực sự chạy?"
    assert contains_raw_phone(text), "/v1/messages: client không nhận SĐT đã khôi phục"


def test_4b_passthrough_anthropic_route_runs_pii_guardrail(
    anthropic_passthrough_client, mock_cloud, findings
):
    error: str | None = None
    text = ""
    try:
        message = anthropic_passthrough_client.messages.create(
            model="claude-mock",
            max_tokens=256,
            messages=[{"role": "user", "content": unique_prompt(f"SĐT {PHONE}, gọi lại giúp")}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    sent = _anthropic_sent(mock_cloud)
    findings["4b_passthrough"] = {
        "error": error,
        "provider_calls": len(mock_cloud.requests()),
        "provider_saw_raw_phone": contains_raw_phone(sent),
        "client_got_restored": contains_raw_phone(text),
    }

    assert error is None, f"Passthrough lỗi: {error}"
    assert not contains_raw_phone(sent), "Passthrough /anthropic: provider nhận SĐT thô"
    assert "<PHONE_1>" in sent, "Passthrough: không thấy placeholder — guardrail có thực sự chạy?"


@pytest.mark.xfail(
    strict=True,
    reason="Lần chạy 1: post_call không chạy trên passthrough /anthropic, client nhận placeholder",
)
def test_4c_passthrough_restores_pii_for_client(anthropic_passthrough_client):
    message = anthropic_passthrough_client.messages.create(
        model="claude-mock",
        max_tokens=256,
        messages=[{"role": "user", "content": unique_prompt(f"SĐT {PHONE}, xác nhận giúp")}],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    assert contains_raw_phone(text)


# ---------------------------------------------------------------------------
# 5. Metering: usage event ghi sang Redis Streams của Bến, có token và chi phí đúng
# ---------------------------------------------------------------------------
def test_5a_usage_event_has_tokens_and_expected_cost(openai_client, redis_client, findings):
    raw = openai_client.chat.completions.with_raw_response.create(
        model="cloud-small",
        messages=[{"role": "user", "content": unique_prompt("Phí giao hàng nội thành?")}],
    )
    completion = raw.parse()
    call_id = raw.headers.get("x-litellm-call-id", "")
    event = wait_usage_event(redis_client, call_id)
    findings["5a_usage_non_stream"] = {"call_id_header": call_id, "event": event}

    assert call_id, "Proxy không trả x-litellm-call-id"
    assert event, "Không có usage event cho call id trong 10 s"
    tokens_in, tokens_out = int(event["tokens_in"]), int(event["tokens_out"])
    assert tokens_in == completion.usage.prompt_tokens
    assert tokens_out == completion.usage.completion_tokens
    expected_cost = tokens_in * 0.000001 + tokens_out * 0.000005
    assert float(event["cost_usd"]) == pytest.approx(expected_cost, rel=0.01)


def test_5b_streaming_usage_event_is_recorded(openai_client, redis_client, findings):
    with openai_client.chat.completions.with_streaming_response.create(
        model="cloud-small",
        messages=[{"role": "user", "content": unique_prompt("Giờ làm việc của tổng đài?")}],
        stream=True,
        stream_options={"include_usage": True},
    ) as response:
        call_id = response.headers.get("x-litellm-call-id", "")
        for _ in response.iter_lines():
            pass
    event = wait_usage_event(redis_client, call_id)
    findings["5b_usage_stream"] = {"call_id_header": call_id, "event": event}

    assert event, "Không có usage event cho request streaming"
    assert int(event["tokens_in"]) > 0 and int(event["tokens_out"]) > 0
    assert float(event["cost_usd"]) > 0


# ---------------------------------------------------------------------------
# 6. Không phụ thuộc tính năng enterprise
# ---------------------------------------------------------------------------
ENTERPRISE_MARKERS = (
    "litellm-enterprise",
    "litellm_enterprise",
    "premium user",
    "Enterprise user",
    "LITELLM_LICENSE",
)


def test_6_runs_without_enterprise_license(proxy_logs, compose_run, spike_dir, findings):
    container_env = compose_run("exec", "-T", "litellm", "env")
    plugin_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (spike_dir / "config").glob("*.py")
    )
    config_text = (spike_dir / "config" / "config.yaml").read_text(encoding="utf-8")
    logs = proxy_logs()
    log_hits = sorted({m for m in ENTERPRISE_MARKERS if m.lower() in logs.lower()})
    findings["6_enterprise"] = {
        "license_env_present": "LITELLM_LICENSE=" in container_env,
        "plugin_imports_enterprise": "enterprise" in plugin_sources.lower(),
        "enterprise_markers_in_logs": log_hits,
    }

    assert "LITELLM_LICENSE=" not in container_env
    assert "enterprise" not in plugin_sources.lower()
    assert "enterprise" not in config_text.lower()
    assert log_hits == [], f"Log proxy nhắc tới tính năng enterprise: {log_hits}"
