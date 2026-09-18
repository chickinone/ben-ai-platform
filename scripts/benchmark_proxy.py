"""Đo overhead của LiteLLM Proxy + plugin so với mock provider trực tiếp.

Chạy bằng virtual key được truyền qua biến môi trường, không nhận key trên command
line và không in key trong báo cáo. Đây là benchmark lặp lại được cho Week 4;
benchmark provider thật vẫn cần API billing/key và được theo dõi riêng.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def percentile(samples: list[float], percentage: float) -> float:
    if not samples:
        raise ValueError("Cần ít nhất một mẫu")
    ordered = sorted(samples)
    index = (len(ordered) - 1) * percentage / 100
    lower, upper = int(index), min(int(index) + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def request_once(url: str, body: dict[str, Any], api_key: str | None) -> float:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{url} → HTTP {exc.code}: {exc.read(300)!r}") from exc
    return (time.perf_counter() - started) * 1000


def measure(run: Callable[[], float], *, warmup: int, requests: int) -> list[float]:
    for _ in range(warmup):
        run()
    return [run() for _ in range(requests)]


def summary(samples: list[float]) -> dict[str, float]:
    return {
        "count": len(samples),
        "p50_ms": round(percentile(samples, 50), 2),
        "p95_ms": round(percentile(samples, 95), 2),
        "mean_ms": round(statistics.fmean(samples), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Đo overhead LiteLLM Proxy trên mock provider")
    parser.add_argument("--requests", type=int, default=30, help="Số mẫu mỗi đường, mặc định 30")
    parser.add_argument("--warmup", type=int, default=3, help="Số request làm nóng mỗi đường")
    parser.add_argument(
        "--proxy-url", default=os.environ.get("BEN_PROXY_URL", "http://127.0.0.1:4000")
    )
    parser.add_argument(
        "--provider-url",
        default=os.environ.get("BEN_MOCK_CLOUD_URL", "http://127.0.0.1:18081"),
    )
    args = parser.parse_args()
    if args.requests <= 0 or args.warmup < 0:
        parser.error("--requests phải dương và --warmup không âm")
    virtual_key = os.environ.get("BEN_BENCHMARK_API_KEY")
    if not virtual_key:
        print(
            "Thiếu BEN_BENCHMARK_API_KEY (virtual key tenant); không truyền key qua command line.",
            file=sys.stderr,
        )
        return 2

    prompt = "Benchmark Week 4: trả lời ngắn gọn bằng một từ."
    provider_body = {"model": "mock-cloud-small", "messages": [{"role": "user", "content": prompt}]}
    proxy_body = dict(provider_body)
    direct = measure(
        lambda: request_once(
            args.provider_url.rstrip("/") + "/v1/chat/completions", provider_body, "sk-mock"
        ),
        warmup=args.warmup,
        requests=args.requests,
    )
    through_proxy = measure(
        lambda: request_once(
            args.proxy_url.rstrip("/") + "/v1/chat/completions", proxy_body, virtual_key
        ),
        warmup=args.warmup,
        requests=args.requests,
    )
    direct_summary = summary(direct)
    proxy_summary = summary(through_proxy)
    print(
        json.dumps(
            {
                "benchmark": "mock-cloud-direct-vs-proxy",
                "direct": direct_summary,
                "proxy": proxy_summary,
                "overhead": {
                    "p50_ms": round(proxy_summary["p50_ms"] - direct_summary["p50_ms"], 2),
                    "p95_ms": round(proxy_summary["p95_ms"] - direct_summary["p95_ms"], 2),
                },
                "note": "Mock-only: không suy diễn latency Claude/OpenAI thật từ kết quả này.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
