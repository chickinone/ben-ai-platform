"""Schema lõi (PROJECT.md §14), role ứng dụng và Row Level Security (ADR-004).

Revision ID: 0001
Revises:
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mỗi phần tử là một câu lệnh; không dùng ký tự % để tránh bị hiểu là tham số.
UPGRADE: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    # Role ứng dụng. Ở compose, script khởi tạo Postgres đã tạo role kèm mật khẩu;
    # khối này để migration chạy được ở môi trường khác (CI).
    """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ben_app') THEN
        CREATE ROLE ben_app LOGIN;
      END IF;
    END
    $$
    """,
    """
    CREATE TABLE tenants (
      id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      slug            text UNIQUE NOT NULL,
      data_residency  text NOT NULL DEFAULT 'any' CHECK (data_residency IN ('any', 'local_only')),
      status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
      created_at      timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE api_keys (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id   uuid NOT NULL REFERENCES tenants(id),
      prefix      text NOT NULL,
      key_hash    bytea NOT NULL UNIQUE,
      scopes      text[] NOT NULL DEFAULT '{chat,embeddings}',
      expires_at  timestamptz,
      revoked_at  timestamptz,
      created_by  text NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX api_keys_tenant_idx ON api_keys (tenant_id)",
    """
    CREATE TABLE policies (
      id          bigserial PRIMARY KEY,
      tenant_id   uuid NOT NULL REFERENCES tenants(id),
      version     int NOT NULL,
      spec        jsonb NOT NULL,
      created_by  text NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, version)
    )
    """,
    """
    CREATE TABLE model_catalog (
      id                      text PRIMARY KEY,
      provider                text NOT NULL,
      tier                    text NOT NULL CHECK (tier IN ('small', 'medium', 'large')),
      price_in                numeric(10,4) NOT NULL,
      price_out               numeric(10,4) NOT NULL,
      cache_read_multiplier   numeric(5,3),
      cache_write_multiplier  numeric(5,3),
      residency               text NOT NULL CHECK (residency IN ('cloud', 'local')),
      enabled                 boolean NOT NULL DEFAULT true
    )
    """,
    """
    CREATE TABLE budgets (
      tenant_id   uuid NOT NULL REFERENCES tenants(id),
      month       date NOT NULL,
      limit_usd   numeric(12,4) NOT NULL,
      spent_usd   numeric(12,6) NOT NULL DEFAULT 0,
      PRIMARY KEY (tenant_id, month)
    )
    """,
    """
    CREATE TABLE usage_events (
      ts            timestamptz NOT NULL,
      tenant_id     uuid NOT NULL,
      key_id        uuid,
      endpoint      text NOT NULL,
      model         text NOT NULL,
      tokens_in     int NOT NULL,
      tokens_out    int NOT NULL,
      cache_read    int NOT NULL DEFAULT 0,
      cache_write   int NOT NULL DEFAULT 0,
      cost_usd      numeric(12,6) NOT NULL,
      latency_ms    int NOT NULL,
      cache_hit     boolean NOT NULL DEFAULT false,
      fallback      boolean NOT NULL DEFAULT false,
      status        smallint NOT NULL,
      trace_id      text NOT NULL
    ) PARTITION BY RANGE (ts)
    """,
    # Partition mặc định cho dev; job tạo partition theo tháng làm ở tuần 4
    "CREATE TABLE usage_events_default PARTITION OF usage_events DEFAULT",
    "CREATE INDEX usage_events_tenant_ts_idx ON usage_events (tenant_id, ts)",
    "CREATE INDEX usage_events_trace_idx ON usage_events (trace_id)",
    """
    CREATE TABLE documents (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id     uuid NOT NULL REFERENCES tenants(id),
      collection    text NOT NULL,
      title         text NOT NULL,
      source_uri    text NOT NULL,
      version       int NOT NULL DEFAULT 1,
      acl_groups    text[] NOT NULL,
      status        text NOT NULL,
      created_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE chunks (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      document_id   uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
      tenant_id     uuid NOT NULL,
      heading_path  text,
      content       text NOT NULL,
      embedding     vector(1024) NOT NULL,
      tsv           tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
      acl_groups    text[] NOT NULL,
      quarantined   boolean NOT NULL DEFAULT false
    )
    """,
    "CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv)",
    "CREATE INDEX chunks_acl_idx ON chunks USING gin (acl_groups)",
    "CREATE INDEX chunks_tenant_idx ON chunks (tenant_id)",
    """
    CREATE TABLE prompts (
      id          bigserial PRIMARY KEY,
      tenant_id   uuid NOT NULL REFERENCES tenants(id),
      name        text NOT NULL,
      version     int NOT NULL,
      template    text NOT NULL,
      eval_score  jsonb,
      labels      text[] NOT NULL DEFAULT '{}',
      UNIQUE (tenant_id, name, version)
    )
    """,
    """
    CREATE TABLE tools (
      id            text PRIMARY KEY,
      mcp_url       text NOT NULL,
      risk_level    text NOT NULL CHECK (risk_level IN ('read', 'write', 'external')),
      input_schema  jsonb NOT NULL,
      approved_by   text,
      approved_at   timestamptz
    )
    """,
    """
    CREATE TABLE agent_runs (
      id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id   uuid NOT NULL,
      agent       text NOT NULL,
      state       text NOT NULL,
      input       jsonb NOT NULL,
      steps       jsonb NOT NULL DEFAULT '[]',
      cost_usd    numeric(12,6) NOT NULL DEFAULT 0,
      started_by  text NOT NULL,
      updated_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE approvals (
      id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      run_id        uuid NOT NULL REFERENCES agent_runs(id),
      step          int NOT NULL,
      tool          text NOT NULL,
      arguments     jsonb NOT NULL,
      requested_at  timestamptz NOT NULL DEFAULT now(),
      decided_by    text,
      decision      text CHECK (decision IN ('approved', 'rejected', 'expired')),
      reason        text
    )
    """,
    """
    CREATE TABLE audit_logs (
      id        bigserial PRIMARY KEY,
      ts        timestamptz NOT NULL DEFAULT now(),
      actor     text NOT NULL,
      action    text NOT NULL,
      resource  text NOT NULL,
      detail    jsonb NOT NULL
    )
    """,
    # --- Row Level Security cho bảng chứa nội dung (ADR-004) ---
    # Chưa đặt app.tenant_id thì không thấy dòng nào.
    "ALTER TABLE documents ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY tenant_isolation ON documents
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """,
    "ALTER TABLE chunks ENABLE ROW LEVEL SECURITY",
    """
    CREATE POLICY tenant_isolation ON chunks
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """,
    # --- Quyền cho role ứng dụng ---
    "GRANT USAGE ON SCHEMA public TO ben_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ben_app",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ben_app",
    # Audit log chỉ được ghi thêm (NFR-13)
    "REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM ben_app",
    "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM ben_app",
]

DOWNGRADE: list[str] = [
    "DROP TABLE IF EXISTS audit_logs",
    "DROP TABLE IF EXISTS approvals",
    "DROP TABLE IF EXISTS agent_runs",
    "DROP TABLE IF EXISTS tools",
    "DROP TABLE IF EXISTS prompts",
    "DROP TABLE IF EXISTS chunks",
    "DROP TABLE IF EXISTS documents",
    "DROP TABLE IF EXISTS usage_events",
    "DROP TABLE IF EXISTS budgets",
    "DROP TABLE IF EXISTS model_catalog",
    "DROP TABLE IF EXISTS policies",
    "DROP TABLE IF EXISTS api_keys",
    "DROP TABLE IF EXISTS tenants",
    # Giữ extension vector và role ben_app: có thể đang được dùng ngoài migration này
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
