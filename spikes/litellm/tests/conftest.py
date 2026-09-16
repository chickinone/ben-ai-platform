import json
import os
import subprocess
from pathlib import Path

import anthropic
import httpx
import openai
import pytest
import redis

LITELLM_URL = os.environ.get("SPIKE_LITELLM_URL", "http://127.0.0.1:4000")
MOCK_CLOUD_URL = os.environ.get("SPIKE_MOCK_CLOUD_URL", "http://127.0.0.1:18081")
MOCK_LOCAL_URL = os.environ.get("SPIKE_MOCK_LOCAL_URL", "http://127.0.0.1:18082")
REDIS_PORT = int(os.environ.get("SPIKE_REDIS_PORT", "16379"))
MASTER_KEY = "sk-ben-spike-master"

SPIKE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SPIKE_DIR.parents[1]
RESULTS_FILE = SPIKE_DIR / "results" / "findings.json"


class Mock:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def requests(self) -> list[dict]:
        return httpx.get(f"{self.base_url}/_requests", timeout=5).json()

    def reset(self) -> None:
        httpx.delete(f"{self.base_url}/_requests", timeout=5)
        self.fail(False)

    def fail(self, value: bool) -> None:
        httpx.post(f"{self.base_url}/_fail", json={"fail": value}, timeout=5)


@pytest.fixture(scope="session")
def mock_cloud() -> Mock:
    return Mock(MOCK_CLOUD_URL)


@pytest.fixture(scope="session")
def mock_local() -> Mock:
    return Mock(MOCK_LOCAL_URL)


@pytest.fixture(scope="session")
def redis_client() -> redis.Redis:
    return redis.Redis(host="127.0.0.1", port=REDIS_PORT, decode_responses=True)


@pytest.fixture(autouse=True)
def clean_state(mock_cloud, mock_local, redis_client):
    mock_cloud.reset()
    mock_local.reset()
    redis_client.flushdb()
    yield
    mock_cloud.fail(False)
    mock_local.fail(False)


@pytest.fixture(scope="session")
def openai_client() -> openai.OpenAI:
    return openai.OpenAI(base_url=f"{LITELLM_URL}/v1", api_key=MASTER_KEY, max_retries=0)


@pytest.fixture(scope="session")
def anthropic_unified_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(base_url=LITELLM_URL, api_key=MASTER_KEY, max_retries=0)


@pytest.fixture(scope="session")
def anthropic_passthrough_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        base_url=f"{LITELLM_URL}/anthropic",
        api_key=MASTER_KEY,
        default_headers={"Authorization": f"Bearer {MASTER_KEY}"},
        max_retries=0,
    )


def compose(*args: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "-f", str(SPIKE_DIR / "docker-compose.yml"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout + result.stderr


@pytest.fixture(scope="session")
def compose_run():
    return compose


@pytest.fixture(scope="session")
def spike_dir() -> Path:
    return SPIKE_DIR


@pytest.fixture(scope="session")
def proxy_logs():
    return lambda: compose("logs", "litellm", "--no-log-prefix")


@pytest.fixture(scope="session")
def findings():
    data: dict = {}
    yield data
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
