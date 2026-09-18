# Bến AI Platform

Nền tảng AI nội bộ đa tenant có quản trị dữ liệu: một cổng duy nhất để các team dùng Claude, GPT, model local, RAG và agent — an toàn với dữ liệu, đo được chi phí, kiểm chứng được chất lượng.

- Tổng quan toàn dự án: [docs/PROJECT.md](docs/PROJECT.md)
- Yêu cầu (nguồn sự thật cho FR/NFR): [docs/requirements.md](docs/requirements.md)
- Kiến trúc: [C4 Context](docs/architecture/c4-context.md) · [C4 Container](docs/architecture/c4-container.md)
- Quyết định kiến trúc: [docs/adr/](docs/adr/README.md)
- Threat model: [docs/threat-model.md](docs/threat-model.md)
- Kịch bản demo (định nghĩa "xong"): [docs/demo-script.md](docs/demo-script.md)

## Trạng thái

| Tuần | Nội dung | Trạng thái |
|---|---|---|
| 1 | Yêu cầu, C4 cấp 1–2, threat model sơ bộ, ADR 001–005, kịch bản demo, thang phân loại (nháp) | ✅ bản đầu, chờ review |
| 2 | Khung repo, Docker Compose, migration schema lõi, CI, gateway `/healthz` `/readyz` | ✅ `up` 151 s, 6/6 dịch vụ đạt (`scripts/verify_stack.py`) |
| 3 | Gateway lõi trên LiteLLM Proxy ([ADR-017](docs/adr/017-litellm-proxy-as-gateway-core.md)): plugin, virtual key, ngân sách, 3 tenant demo, allow-list endpoint | ✅ |
| 4 | Policy YAML → LiteLLM team UUID; Redis Streams → Postgres; rate limit Redis dùng chung | ✅ mock nội bộ; 🔶 Claude/OpenAI thật và đối soát provider để Pending |
| 5 | Guardrails PII/injection: recognizer tiếng Việt, 4 mode policy, audit append-only, báo cáo eval | ✅ mock nội bộ: 500/500 mẫu synthetic; chưa thay thế kiểm thử dữ liệu doanh nghiệp thật |
| 6–16 | Xem [lộ trình](docs/PROJECT.md#22-lộ-trình-16-tuần) | ⏳ |

## Chạy trong 5 phút

Cần: Docker Desktop, Python 3.12+. RAM khuyến nghị 16 GB (bản đầy đủ có Langfuse + ClickHouse nên thoải mái hơn với 32 GB).

**Windows (PowerShell):**

```powershell
.\scripts\tasks.ps1 init       # tạo .env với mật khẩu ngẫu nhiên
.\scripts\tasks.ps1 venv       # cài dependency cho seed/test
.\scripts\tasks.ps1 up-core    # Postgres, Redis, migration, worker metering, LiteLLM gateway
.\scripts\tasks.ps1 seed-demo  # tạo cskh, hr, finance; key dev nằm ngoài Git
.\scripts\tasks.ps1 ps
```

**Linux / macOS:**

```bash
make init
make up-core
make ps
```

Bật thêm observability (OpenTelemetry Collector, Langfuse, ClickHouse): dùng `up` thay cho `up-core`.

Tải model local lần đầu (khoảng 4–5 GB):

```powershell
.\scripts\tasks.ps1 pull-model qwen2.5:7b
```

### Địa chỉ dịch vụ (chỉ lắng nghe trên 127.0.0.1)

| Dịch vụ | URL | Đăng nhập |
|---|---|---|
| LiteLLM Proxy (gateway công khai, ADR-017) | http://localhost:4000 | virtual key của tenant |
| LiteLLM admin (chỉ dev, loopback) | http://localhost:4001/ui | `LITELLM_MASTER_KEY` trong `.env` |
| Mock provider (dev/test) | http://localhost:18081, http://localhost:18082 | — |
| Keycloak | http://localhost:8080 | `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` trong `.env` |
| MinIO console | http://localhost:9001 | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| Langfuse (bản `up`) | http://localhost:3000 | `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` |
| Postgres | localhost:55432 (đổi bằng `POSTGRES_HOST_PORT`), DB `ben` | `POSTGRES_USER` / `POSTGRES_PASSWORD` |
| Ollama | http://localhost:11434 | — |

Người dùng demo trong realm Keycloak `ben` (mật khẩu `ben-dev-only`, **chỉ dùng cho môi trường dev**): `minh` (Platform Admin), `lan` (Tenant Admin CSKH), `hoa` (phòng Kinh doanh), `tuan` (phòng Kỹ thuật), `quan` (Finance), `dpo`.

### Seed tenant demo và gọi thử qua LiteLLM

Tenant là một *team* của LiteLLM; app dùng *virtual key* của team. Đường nhanh cho môi trường dev là:

```powershell
.\scripts\tasks.ps1 seed-demo
python .\scripts\seed_demo_tenants.py --show-keys
```

Script an toàn để chạy lại khi `.demo-keys.json` còn tồn tại; file này bị Git bỏ qua vì chứa key dev và tách key theo URL admin. YAML trong `config/tenants/` là nguồn policy cho UUID, model, budget, RPM/TPM và fallback; seed đồng bộ limit vào cả team (aggregate) lẫn key dev (chặn request). API tenant chỉ dùng `http://localhost:4000`; cổng `4001` dành cho admin/dev và không route Anthropic passthrough.

### Benchmark Week 4 với mock

Sau khi seed, lấy key dev vào biến môi trường (không đưa key vào command line) rồi chạy benchmark. Kết quả là overhead proxy/plugin so với mock trực tiếp; không đại diện cho latency Claude/OpenAI thật.

```powershell
$env:BEN_BENCHMARK_API_KEY = (Get-Content .demo-keys.json | ConvertFrom-Json).'http://127.0.0.1:4001'.cskh
python .\scripts\benchmark_proxy.py --requests 30
```

## Phát triển

```powershell
.\scripts\tasks.ps1 venv    # tạo .venv và cài các package ở chế độ editable
.\scripts\tasks.ps1 lint
.\scripts\tasks.ps1 test
.\scripts\tasks.ps1 test-integration   # cần up-core đang chạy
.\scripts\tasks.ps1 eval-pii            # 500 mẫu PII synthetic, ghi báo cáo có version
```

`eval-pii` không dùng dữ liệu khách hàng. Báo cáo tái lập nằm tại
[`docs/reports/pii_vn_eval.json`](docs/reports/pii_vn_eval.json); trước khi dùng production,
cần chạy thêm bộ mẫu đã được phê duyệt và red-team theo ngữ cảnh nghiệp vụ.

Test migration cần một Postgres có pgvector:

```powershell
# Tạo DB test một lần: docker compose --env-file .env -f deploy/compose/docker-compose.yml exec postgres psql -U ben -d ben -c "CREATE DATABASE ben_test"
$env:BEN_TEST_DATABASE_URL = "postgresql+psycopg://ben:<POSTGRES_PASSWORD>@127.0.0.1:55432/ben_test?connect_timeout=5"
.\.venv\Scripts\python.exe -m pytest services/control-plane/tests
```

## Cấu trúc repo (hiện tại)

```
ben-ai-platform/
├── docs/                    # PROJECT.md, requirements, architecture, adr, threat model, demo, governance
├── libs/
│   ├── ben_common/          # settings, định dạng lỗi chung, request id, log JSON
│   └── ben_telemetry/       # khởi tạo OpenTelemetry
├── services/
│   ├── gateway/             # FastAPI skeleton tuần 2, không còn deploy (ADR-017)
│   ├── control-plane/       # migration Alembic cho schema lõi (API quản trị: tuần 10)
│   └── metering-worker/     # consumer Redis Stream usage → Postgres, idempotent
├── deploy/compose/          # docker-compose.yml, docker-compose.observability.yml, cấu hình Postgres/Keycloak/OTel
├── scripts/                 # tasks.ps1 (Windows), init_env.py
├── .github/workflows/ci.yml # lint, test, test migration, kiểm tra compose
└── Makefile
```
