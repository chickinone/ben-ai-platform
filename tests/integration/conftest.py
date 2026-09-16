"""Test tích hợp với LiteLLM Proxy đang chạy (tasks.ps1 up-core).

Tự bỏ qua toàn bộ khi proxy không chạy. Đọc master key và mật khẩu Redis từ .env.
"""

import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
import redis

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_FILE = Path(__file__).resolve().parent / "results" / "findings.json"

PROXY_URL = os.environ.get("BEN_PROXY_URL", "http://127.0.0.1:4000")
MOCK_CLOUD_URL = os.environ.get("BEN_MOCK_CLOUD_URL", "http://127.0.0.1:18081")
MOCK_LOCAL_URL = os.environ.get("BEN_MOCK_LOCAL_URL", "http://127.0.0.1:18082")


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


DOTENV = read_dotenv(REPO_ROOT / ".env")


def setting(name: str) -> str:
    return os.environ.get(name) or DOTENV.get(name, "")


class Mock:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def requests(self) -> list[dict]:
        return httpx.get(f"{self.base_url}/_requests", timeout=5).json()

    def sent_text(self) -> str:
        return "".join(request["raw"] for request in self.requests())

    def reset(self) -> None:
        httpx.delete(f"{self.base_url}/_requests", timeout=5)
        self.fail(False)

    def fail(self, value: bool) -> None:
        httpx.post(f"{self.base_url}/_fail", json={"fail": value}, timeout=5)


@pytest.fixture(scope="session", autouse=True)
def proxy_available():
    try:
        httpx.get(f"{PROXY_URL}/health/liveliness", timeout=3).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"LiteLLM Proxy không chạy ở {PROXY_URL}: {exc}")


@pytest.fixture(scope="session")
def mock_cloud() -> Mock:
    return Mock(MOCK_CLOUD_URL)


@pytest.fixture(scope="session")
def mock_local() -> Mock:
    return Mock(MOCK_LOCAL_URL)


@pytest.fixture(autouse=True)
def reset_mocks(mock_cloud, mock_local):
    mock_cloud.reset()
    mock_local.reset()
    yield
    mock_cloud.fail(False)
    mock_local.fail(False)


@pytest.fixture(scope="session")
def admin() -> httpx.Client:
    master_key = setting("LITELLM_MASTER_KEY")
    if not master_key:
        pytest.skip("Thiếu LITELLM_MASTER_KEY trong .env")
    with httpx.Client(
        base_url=PROXY_URL, headers={"Authorization": f"Bearer {master_key}"}, timeout=30
    ) as client:
        yield client


def _post_json(client: httpx.Client, path: str, body: dict) -> dict:
    response = client.post(path, json=body)
    if response.is_error:
        raise AssertionError(f"{path} → {response.status_code}: {response.text[:300]}")
    return response.json()


@pytest.fixture
def tenant(admin):
    """Tạo team (= tenant) và virtual key; dọn sau test."""
    keys: list[str] = []
    teams: list[str] = []

    def make(*, models: list[str], max_budget: float | None = None, service: bool = False) -> dict:
        alias = f"it-{uuid.uuid4().hex[:8]}"
        team = _post_json(admin, "/team/new", {"team_alias": alias, "models": models})
        teams.append(team["team_id"])
        body: dict = {
            "team_id": team["team_id"],
            "models": models,
            "key_alias": alias,
            "metadata": {"ben_tenant": alias, **({"ben_service": True} if service else {})},
        }
        if max_budget is not None:
            body["max_budget"] = max_budget
        key = _post_json(admin, "/key/generate", body)
        keys.append(key["key"])
        return {"team_id": team["team_id"], "alias": alias, "key": key["key"]}

    yield make
    if keys:
        admin.post("/key/delete", json={"keys": keys})
    if teams:
        admin.post("/team/delete", json={"team_ids": teams})


def _redis(db: int, decode: bool) -> redis.Redis:
    return redis.Redis(
        host="127.0.0.1",
        port=6379,
        db=db,
        password=setting("REDIS_PASSWORD") or None,
        decode_responses=decode,
    )


@pytest.fixture(scope="session")
def usage_stream() -> redis.Redis:
    return _redis(db=0, decode=True)


@pytest.fixture(scope="session")
def pii_store_redis() -> redis.Redis:
    return _redis(db=2, decode=False)


@pytest.fixture(scope="session")
def findings():
    data: dict = {}
    yield data
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
