"""Kiểm tra các dịch vụ sau khi `up` (tuần 2, NFR-14).

Dùng:  .venv\\Scripts\\python.exe scripts/verify_stack.py
Trả exit code 1 nếu có dịch vụ không đạt.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from collections.abc import Callable
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


def check_litellm_public_edge(env: dict[str, str]) -> str:
    httpx.get("http://127.0.0.1:4000/health/liveliness", timeout=5).raise_for_status()
    blocked = httpx.post("http://127.0.0.1:4000/anthropic/v1/messages", timeout=5)
    assert blocked.status_code == 404, blocked.status_code
    return "liveliness ok; Anthropic passthrough bị chặn"


def check_litellm_admin(env: dict[str, str]) -> str:
    httpx.get("http://127.0.0.1:4001/health/liveliness", timeout=5).raise_for_status()
    return "liveliness ok (loopback)"


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


def check_redis(env: dict[str, str]) -> str:
    assert compose_exec("redis", "redis-cli", "ping").strip() == "PONG"
    return "PONG"


CHECKS: list[tuple[str, Callable[[dict[str, str]], str]]] = [
    ("LiteLLM public edge", check_litellm_public_edge),
    ("LiteLLM admin edge", check_litellm_admin),
    ("Keycloak (user demo)", check_keycloak),
    ("MinIO (4 bucket)", check_minio),
    ("Ollama", check_ollama),
    ("Redis", check_redis),
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
