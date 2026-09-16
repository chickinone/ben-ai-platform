"""Kiểm tra các dịch vụ sau khi `up` (tuần 2, NFR-14).

Dùng:  .venv\\Scripts\\python.exe scripts/verify_stack.py
Trả exit code 1 nếu có dịch vụ không đạt.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    ".env",
    "-f",
    "deploy/compose/docker-compose.yml",
    "-f",
    "deploy/compose/docker-compose.observability.yml",
]
EXPECTED_BUCKETS = {"ben-docs", "ben-reports", "ben-policy-bundles", "langfuse"}
DEMO_PASSWORD = "ben-dev-only"


def read_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def compose_exec(*args: str) -> str:
    result = subprocess.run(
        [*COMPOSE, "exec", "-T", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


def check_gateway(env: dict[str, str]) -> str:
    body = httpx.get("http://127.0.0.1:8000/readyz", timeout=5).raise_for_status().json()
    assert body["status"] == "ok", body
    return f"readyz {body['checks']}"


def check_litellm(env: dict[str, str]) -> str:
    httpx.get("http://127.0.0.1:4000/health/liveliness", timeout=5).raise_for_status()
    return "liveliness ok"


def check_keycloak(env: dict[str, str]) -> str:
    response = httpx.post(
        "http://127.0.0.1:8080/realms/ben/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "ben-demo-cli",
            "username": "lan",
            "password": DEMO_PASSWORD,
        },
        timeout=10,
    ).raise_for_status()
    token = response.json()["access_token"]
    payload_part = token.split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)))
    groups = set(payload.get("groups", []))
    assert {"all-staff", "dept-cskh"} <= groups, groups
    return f"user lan đăng nhập được, groups={sorted(groups)}"


def check_minio(env: dict[str, str]) -> str:
    compose_exec(
        "minio",
        "mc",
        "alias",
        "set",
        "verify",
        "http://127.0.0.1:9000",
        env["MINIO_ROOT_USER"],
        env["MINIO_ROOT_PASSWORD"],
    )
    listing = compose_exec("minio", "mc", "ls", "verify")
    buckets = {line.split()[-1].rstrip("/") for line in listing.splitlines() if line.strip()}
    missing = EXPECTED_BUCKETS - buckets
    assert not missing, f"thiếu bucket {sorted(missing)}"
    return f"buckets={sorted(buckets)}"


def check_ollama(env: dict[str, str]) -> str:
    version = httpx.get("http://127.0.0.1:11434/api/version", timeout=5).raise_for_status().json()
    return f"version {version.get('version')}"


def check_langfuse_receives_gateway_trace(env: dict[str, str]) -> str:
    started = datetime.now(UTC)
    # /docs là route được instrument (healthz/readyz bị loại khỏi trace)
    for _ in range(3):
        httpx.get("http://127.0.0.1:8000/docs", timeout=5)
    auth = (env["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"], env["LANGFUSE_INIT_PROJECT_SECRET_KEY"])
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        # Langfuse v4 bỏ /api/public/traces; dữ liệu span đọc qua Observations API v2
        response = httpx.get(
            "http://127.0.0.1:3000/api/public/v2/observations",
            params={"limit": 100},
            auth=auth,
            timeout=10,
        )
        response.raise_for_status()
        fresh = [
            obs
            for obs in response.json().get("data", [])
            if "/docs" in str(obs.get("name"))
            and datetime.fromisoformat(str(obs["startTime"]).replace("Z", "+00:00")) >= started
        ]
        if fresh:
            return f"{len(fresh)} observation mới từ gateway, ví dụ '{fresh[0]['name']}'"
        time.sleep(5)
    raise AssertionError("không thấy span GET /docs của gateway trên Langfuse sau 120 s")


CHECKS: list[tuple[str, Callable[[dict[str, str]], str]]] = [
    ("Gateway FastAPI", check_gateway),
    ("LiteLLM Proxy", check_litellm),
    ("Keycloak (user demo)", check_keycloak),
    ("MinIO (4 bucket)", check_minio),
    ("Ollama", check_ollama),
    ("Langfuse nhận trace gateway", check_langfuse_receives_gateway_trace),
]


def main() -> int:
    env = read_dotenv()
    failures = 0
    for name, check in CHECKS:
        try:
            detail = check(env)
            print(f"[OK]   {name}: {detail}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {name}: {type(exc).__name__}: {str(exc)[:300]}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} dịch vụ đạt")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
