"""Test migration trên Postgres thật có pgvector.

Bỏ qua khi không có BEN_TEST_DATABASE_URL, ví dụ:
postgresql+psycopg://ben:<mật khẩu>@localhost:5432/ben_test
Dùng database riêng cho test: test chạy downgrade toàn bộ schema.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError

TEST_DATABASE_URL = os.environ.get("BEN_TEST_DATABASE_URL")
SERVICE_DIR = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="Cần BEN_TEST_DATABASE_URL trỏ tới Postgres có pgvector"
)

CORE_TABLES = {
    "tenants",
    "api_keys",
    "policies",
    "model_catalog",
    "budgets",
    "usage_events",
    "usage_event_receipts",
    "documents",
    "chunks",
    "prompts",
    "tools",
    "agent_runs",
    "approvals",
    "audit_logs",
}


def alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=SERVICE_DIR,
        env={**os.environ, "BEN_MIGRATION_DATABASE_URL": TEST_DATABASE_URL},
        check=True,
    )


@pytest.fixture(scope="module")
def engine():
    alembic("downgrade", "base")
    alembic("upgrade", "head")
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


def test_core_tables_exist(engine):
    assert set(inspect(engine).get_table_names()) >= CORE_TABLES


def test_app_role_can_append_but_not_modify_audit_logs(engine):
    with engine.connect() as conn:
        conn.execute(text("SET ROLE ben_app"))
        conn.execute(
            text(
                "INSERT INTO audit_logs (actor, action, resource, detail) "
                "VALUES ('test', 'test.run', 'test', '{}')"
            )
        )
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("UPDATE audit_logs SET actor = 'attacker'"))
        conn.rollback()


def test_app_role_sees_only_its_tenant_documents(engine):
    with engine.connect() as conn:
        tenant_a, tenant_b = (
            conn.execute(
                text("INSERT INTO tenants (slug) VALUES (:slug) RETURNING id"), {"slug": slug}
            ).scalar_one()
            for slug in ("rls-a", "rls-b")
        )
        for tenant_id in (tenant_a, tenant_b):
            conn.execute(
                text(
                    "INSERT INTO documents "
                    "(tenant_id, collection, title, source_uri, acl_groups, status) "
                    "VALUES (:tenant_id, 'c', 't', 's3://x', '{all-staff}', 'ready')"
                ),
                {"tenant_id": tenant_id},
            )

        conn.execute(text("SET ROLE ben_app"))
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0

        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)})
        rows = conn.execute(text("SELECT tenant_id FROM documents")).scalars().all()
        assert rows == [tenant_a]
        conn.rollback()


def test_downgrade_and_upgrade_are_repeatable(engine):
    alembic("downgrade", "base")
    assert not CORE_TABLES & set(inspect(engine).get_table_names())
    alembic("upgrade", "head")
    assert set(inspect(engine).get_table_names()) >= CORE_TABLES
