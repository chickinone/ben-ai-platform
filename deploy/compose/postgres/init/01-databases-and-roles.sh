#!/bin/bash
# Chạy một lần khi volume Postgres còn trống.
# Tạo role ứng dụng ben_app (ADR-004) và database riêng cho Keycloak, Langfuse.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v app_password="$BEN_APP_DB_PASSWORD" <<'EOSQL'
CREATE ROLE ben_app LOGIN PASSWORD :'app_password';
CREATE DATABASE keycloak;
CREATE DATABASE langfuse;
CREATE DATABASE litellm;
EOSQL
