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
RESULTS_FILE = Path(
    os.environ.get(
        "BEN_INTEGRATION_FINDINGS_FILE",
        str(Path(__file__).resolve().parent / "results" / "findings.json"),
    )
)

PROXY_URL = os.environ.get("BEN_PROXY_URL", "http://127.0.0.1:4000")
ADMIN_URL = os.environ.get("BEN_LITELLM_ADMIN_URL", "http://127.0.0.1:4001")
MOCK_CLOUD_URL = os.environ.get("BEN_MOCK_CLOUD_URL", "http://127.0.0.1:18081")
MOCK_LOCAL_URL = os.environ.get("BEN_MOCK_LOCAL_URL", "http://127.0.0.1:18082")
REDIS_HOST = os.environ.get("BEN_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("BEN_REDIS_PORT", "6379"))


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
        base_url=ADMIN_URL, headers={"Authorization": f"Bearer {master_key}"}, timeout=30
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

    def make(
        *,
        models: list[str],
        max_budget: float | None = None,
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        service: bool = False,
        pii_mode: str | None = None,
        pii_restore: bool | None = None,
        injection_mode: str | None = None,
    ) -> dict:
        team_id = str(uuid.uuid4())
        alias = f"it-{uuid.uuid4().hex[:8]}"
        team_body: dict = {"team_id": team_id, "team_alias": alias, "models": models}
        if rpm_limit is not None:
            team_body["rpm_limit"] = rpm_limit
        if tpm_limit is not None:
            team_body["tpm_limit"] = tpm_limit
        team = _post_json(admin, "/team/new", team_body)
        teams.append(team["team_id"])
        body: dict = {
            "team_id": team["team_id"],
            "models": models,
            "key_alias": alias,
            "metadata": {
                "ben_tenant": alias,
                **({"ben_rpm_limit": rpm_limit} if rpm_limit is not None else {}),
                **({"ben_tpm_limit": tpm_limit} if tpm_limit is not None else {}),
                **({"ben_service": True} if service else {}),
                **({"ben_pii_mode": pii_mode} if pii_mode is not None else {}),
                **({"ben_pii_restore": pii_restore} if pii_restore is not None else {}),
                **({"ben_injection_mode": injection_mode} if injection_mode is not None else {}),
            },
        }
        if max_budget is not None:
            body["max_budget"] = max_budget
        if rpm_limit is not None:
            body["rpm_limit"] = rpm_limit
        if tpm_limit is not None:
            body["tpm_limit"] = tpm_limit
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
        host=REDIS_HOST,
        port=REDIS_PORT,
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
