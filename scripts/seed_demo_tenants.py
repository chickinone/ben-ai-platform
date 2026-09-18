"""Seed idempotent ba tenant demo vào LiteLLM.

Chạy sau khi ``tasks.ps1 up-core``. Secret virtual key chỉ được in khi vừa tạo;
script ghi bản dev vào ``.demo-keys.json`` (đã nằm trong .gitignore) để lần chạy
sau không phải tạo key mới.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYS_FILE = REPO_ROOT / ".demo-keys.json"
ADMIN_URL = os.environ.get("BEN_LITELLM_ADMIN_URL", "http://127.0.0.1:4001").rstrip("/")
POLICIES_DIR = REPO_ROOT / "config" / "tenants"


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def load_key_store() -> dict[str, dict[str, str]]:
    if not KEYS_FILE.exists():
        return {}
    try:
        value = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{KEYS_FILE.name} không phải JSON hợp lệ: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{KEYS_FILE.name} phải là JSON object")
    # Nâng cấp file của phiên bản seed đầu: alias -> key.
    if all(isinstance(key, str) for key in value.values()):
        return {ADMIN_URL: {str(name): str(key) for name, key in value.items()}}
    return {
        str(url): {str(name): str(key) for name, key in keys.items()}
        for url, keys in value.items()
        if isinstance(keys, dict)
    }


def save_key_store(key_store: dict[str, dict[str, str]]) -> None:
    KEYS_FILE.write_text(
        json.dumps(key_store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_policies() -> list[dict[str, Any]]:
    policies: list[dict[str, Any]] = []
    for path in sorted(POLICIES_DIR.glob("*.yaml")):
        policy = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(policy, dict):
            raise RuntimeError(f"{path}: policy phải là YAML object")
        tenant = policy.get("tenant")
        limits = policy.get("limits")
        models = policy.get("models")
        if (
            not isinstance(tenant, dict)
            or not isinstance(limits, dict)
            or not isinstance(models, dict)
        ):
            raise RuntimeError(f"{path}: cần tenant, limits và models")
        try:
            tenant["id"] = str(uuid.UUID(str(tenant["id"])))
            tenant["slug"] = str(tenant["slug"])
            tenant["data_residency"] = str(tenant["data_residency"])
            limits["monthly_budget_usd"] = float(limits["monthly_budget_usd"])
            limits["warning_budget_usd"] = float(limits["warning_budget_usd"])
            limits["rpm"] = int(limits["rpm"])
            limits["tpm"] = int(limits["tpm"])
            policy["version"] = int(policy["version"])
            models["allow"] = [str(model) for model in models["allow"]]
            models["fallbacks"] = dict(models.get("fallbacks") or {})
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"{path}: policy không hợp lệ: {exc}") from exc
        if tenant["data_residency"] not in {"any", "local_only"}:
            raise RuntimeError(f"{path}: data_residency phải là any hoặc local_only")
        if (
            not models["allow"]
            or policy["version"] <= 0
            or limits["rpm"] <= 0
            or limits["tpm"] <= 0
            or limits["warning_budget_usd"] > limits["monthly_budget_usd"]
        ):
            raise RuntimeError(f"{path}: allow không được rỗng; warning không được lớn hơn budget")
        policies.append(policy)
    if not policies:
        raise RuntimeError(f"Không tìm thấy policy YAML tại {POLICIES_DIR}")
    return policies


def control_database_url(dotenv: dict[str, str]) -> str:
    port = os.environ.get("POSTGRES_HOST_PORT") or dotenv.get("POSTGRES_HOST_PORT", "55432")
    return os.environ.get("BEN_CONTROL_DATABASE_URL") or (
        f"postgresql://ben_app:{dotenv['BEN_APP_DB_PASSWORD']}@127.0.0.1:{port}/ben"
    )


def sync_control_plane(policy: dict[str, Any], database_url: str) -> None:
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("Thiếu psycopg; chạy .\\scripts\\tasks.ps1 venv trước.") from exc
    tenant = policy["tenant"]
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, slug, data_residency)
            VALUES (%(id)s, %(slug)s, %(data_residency)s)
            ON CONFLICT (id) DO UPDATE
              SET slug = EXCLUDED.slug, data_residency = EXCLUDED.data_residency
            """,
            tenant,
        )
        cursor.execute(
            """
            INSERT INTO policies (tenant_id, version, spec, created_by)
            VALUES (%(tenant_id)s, %(version)s, %(spec)s, 'seed-demo')
            ON CONFLICT (tenant_id, version) DO UPDATE
              SET spec = EXCLUDED.spec, created_by = EXCLUDED.created_by
            """,
            {
                "tenant_id": tenant["id"],
                "version": policy["version"],
                "spec": Jsonb(policy),
            },
        )


def request_json(method: str, path: str, token: str, body: dict[str, Any] | None = None) -> Any:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{ADMIN_URL}{path}",
        data=payload,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{method} {path} → HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Không kết nối được LiteLLM admin ở {ADMIN_URL}: {exc.reason}") from exc


def items(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, dict):
        response = response.get("data", response.get("teams", []))
    return (
        [item for item in response if isinstance(item, dict)] if isinstance(response, list) else []
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed tenant demo cskh, hr và finance vào LiteLLM")
    parser.add_argument("--show-keys", action="store_true", help="in lại các key dev đã lưu cục bộ")
    parser.add_argument(
        "--recreate-demo",
        action="store_true",
        help="xoá và tạo lại các team demo có UUID cũ (chỉ dùng cho dữ liệu demo)",
    )
    args = parser.parse_args()

    dotenv = read_dotenv(REPO_ROOT / ".env")
    master_key = os.environ.get("LITELLM_MASTER_KEY") or dotenv.get("LITELLM_MASTER_KEY")
    if not master_key:
        print("Thiếu LITELLM_MASTER_KEY; chạy .\\scripts\\tasks.ps1 init trước.", file=sys.stderr)
        return 2

    policies = load_policies()
    key_store = load_key_store()
    saved_keys = key_store.setdefault(ADMIN_URL, {})
    teams = items(request_json("GET", "/team/list", master_key))
    by_alias = {str(team.get("team_alias")): team for team in teams if team.get("team_alias")}

    for policy in policies:
        tenant = policy["tenant"]
        limits = policy["limits"]
        models = policy["models"]
        alias = tenant["slug"]
        rate_metadata = {
            "ben_tenant": alias,
            "ben_policy_version": policy["version"],
            "ben_rpm_limit": limits["rpm"],
            "ben_tpm_limit": limits["tpm"],
        }
        sync_control_plane(policy, control_database_url(dotenv))
        team = by_alias.get(alias)
        if team is not None and str(team.get("team_id")) != tenant["id"]:
            if not args.recreate_demo:
                raise RuntimeError(
                    f"Tenant demo {alias} đang dùng team_id {team.get('team_id')}, khác UUID chuẩn "
                    f"{tenant['id']}. Chạy lại với --recreate-demo để thay team demo cũ."
                )
            request_json("POST", "/team/delete", master_key, {"team_ids": [team["team_id"]]})
            saved_keys.pop(alias, None)
            team = None
            print(f"Đã xoá team demo UUID cũ của {alias}.")
        if team is None:
            team = request_json(
                "POST",
                "/team/new",
                master_key,
                {
                    "team_id": tenant["id"],
                    "team_alias": alias,
                    "models": models["allow"],
                    "max_budget": limits["monthly_budget_usd"],
                    "soft_budget": limits["warning_budget_usd"],
                    "rpm_limit": limits["rpm"],
                    "tpm_limit": limits["tpm"],
                    "router_settings": {"fallbacks": models["fallbacks"]},
                    "metadata": rate_metadata,
                },
            )
            print(f"Tạo tenant {alias} (team_id={team['team_id']}).")
        else:
            request_json(
                "POST",
                "/team/update",
                master_key,
                {
                    "team_id": tenant["id"],
                    "models": models["allow"],
                    "max_budget": limits["monthly_budget_usd"],
                    "soft_budget": limits["warning_budget_usd"],
                    "rpm_limit": limits["rpm"],
                    "tpm_limit": limits["tpm"],
                    "router_settings": {"fallbacks": models["fallbacks"]},
                    "metadata": rate_metadata,
                },
            )
            print(f"Tenant {alias} đã tồn tại (team_id={team.get('team_id')}).")

        key_policy = {
            "models": models["allow"],
            # LiteLLM thực thi RPM/TPM tin cậy ở virtual key. Team vẫn giữ budget
            # aggregate; bản sao ở key chặn burst ngay trên đường request.
            "max_budget": limits["monthly_budget_usd"],
            "rpm_limit": limits["rpm"],
            "tpm_limit": limits["tpm"],
            "metadata": {**rate_metadata, "ben_demo": True},
        }
        needs_replacement_alias = False
        if alias in saved_keys:
            try:
                request_json(
                    "POST",
                    "/key/update",
                    master_key,
                    {"key": saved_keys[alias], **key_policy},
                )
            except RuntimeError:
                # Key cục bộ có thể thuộc stack cũ hoặc đã bị rotate/revoke. Chỉ tạo
                # lại key dev của alias này, không đụng key production nào khác.
                saved_keys.pop(alias, None)
                needs_replacement_alias = True
                print(f"Key dev cũ của {alias} không còn hợp lệ; sẽ tạo key mới.")
        if alias not in saved_keys:
            # LiteLLM áp đặt unique alias toàn cục. Khi secret dev cũ bị revoke/rotate,
            # ta không biết secret để xoá nó an toàn; dùng alias mới thay vì đụng key lạ.
            key_alias = (
                f"{alias}-demo-{uuid.uuid4().hex[:8]}"
                if needs_replacement_alias
                else f"{alias}-demo"
            )
            key = request_json(
                "POST",
                "/key/generate",
                master_key,
                {
                    "team_id": tenant["id"],
                    "key_alias": key_alias,
                    **key_policy,
                },
            )
            saved_keys[alias] = key["key"]
            print(f"Tạo virtual key cho {alias} (chỉ dev).")

    save_key_store(key_store)
    if args.show_keys:
        for alias in sorted(saved_keys):
            print(f"{alias}={saved_keys[alias]}")
    else:
        print(
            f"Hoàn tất. Key dev được lưu ngoài Git tại {KEYS_FILE.name}; dùng --show-keys để xem."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
