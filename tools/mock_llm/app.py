"""Mock provider cho thử nghiệm LiteLLM.

Giả lập OpenAI Chat Completions và Anthropic Messages (thường + streaming).
Ghi lại nguyên văn body mọi request để test kiểm tra provider thực sự nhận được gì.
Câu trả lời lặp lại tin nhắn cuối của user để test kiểm tra được việc khôi phục PII.
"""

import asyncio
import json
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

NAME = os.environ.get("MOCK_NAME", "mock")
CHUNK_SIZE = 3  # nhỏ để placeholder như <PHONE_1> bị cắt qua nhiều chunk

app = FastAPI(title=f"mock-llm {NAME}")
state: dict[str, Any] = {"requests": [], "fail": False}


def record(path: str, raw: bytes) -> dict:
    body = json.loads(raw or b"{}")
    state["requests"].append({"path": path, "raw": raw.decode("utf-8"), "body": body})
    return body


def last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        return " ".join(
            part.get("text", "")
            for part in content or []
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def pieces(text: str) -> list[str]:
    return [text[i : i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]


def sse(payload: dict, event: str | None = None) -> str:
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "name": NAME}


@app.get("/_requests")
async def list_requests() -> list[dict]:
    return state["requests"]


@app.delete("/_requests")
async def clear_requests() -> dict:
    state["requests"].clear()
    return {"cleared": True}


@app.post("/_fail")
async def set_fail(request: Request) -> dict:
    state["fail"] = bool((await request.json()).get("fail"))
    return {"fail": state["fail"]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = record("/v1/chat/completions", await request.body())
    if state["fail"]:
        return JSONResponse(
            {"error": {"message": f"{NAME} unavailable", "type": "server_error"}}, status_code=503
        )

    text = f"[{NAME}] ECHO: {last_user_text(body.get('messages', []))}"
    usage = {
        "prompt_tokens": max(1, len(json.dumps(body.get("messages", []))) // 4),
        "completion_tokens": max(1, len(text) // 4),
    }
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    base = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "created": int(time.time()),
        "model": body.get("model", "mock"),
    }

    if not body.get("stream"):
        return {
            **base,
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }

    async def events():
        chunk = {**base, "object": "chat.completion.chunk"}
        yield sse(
            {**chunk, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}
        )
        for piece in pieces(text):
            yield sse({**chunk, "choices": [{"index": 0, "delta": {"content": piece}}]})
            await asyncio.sleep(0)
        yield sse({**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        if (body.get("stream_options") or {}).get("include_usage"):
            yield sse({**chunk, "choices": [], "usage": usage})
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    body = record("/v1/messages", await request.body())
    if state["fail"]:
        return JSONResponse(
            {"type": "error", "error": {"type": "api_error", "message": f"{NAME} unavailable"}},
            status_code=503,
        )

    text = f"[{NAME}] ECHO: {last_user_text(body.get('messages', []))}"
    input_tokens = max(1, len(json.dumps(body.get("messages", []))) // 4)
    output_tokens = max(1, len(text) // 4)
    message = {
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "mock"),
    }

    if not body.get("stream"):
        return {
            **message,
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }

    async def events():
        yield sse(
            {
                "type": "message_start",
                "message": {
                    **message,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": 1},
                },
            },
            "message_start",
        )
        yield sse(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            "content_block_start",
        )
        for piece in pieces(text):
            yield sse(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": piece},
                },
                "content_block_delta",
            )
            await asyncio.sleep(0)
        yield sse({"type": "content_block_stop", "index": 0}, "content_block_stop")
        yield sse(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": output_tokens},
            },
            "message_delta",
        )
        yield sse({"type": "message_stop"}, "message_stop")

    return StreamingResponse(events(), media_type="text/event-stream")
