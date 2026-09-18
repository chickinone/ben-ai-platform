COMPOSE_CORE = docker compose --env-file .env -f deploy/compose/docker-compose.yml
COMPOSE_ALL  = $(COMPOSE_CORE) -f deploy/compose/docker-compose.observability.yml
PY           = .venv/bin/python
MODEL       ?= qwen2.5:7b

.PHONY: help init venv lint fmt test test-integration seed-demo config up up-core down ps logs migrate pull-model

help:        ## Liệt kê tác vụ
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

init:        ## Tạo .env với mật khẩu ngẫu nhiên
	python3 scripts/init_env.py

venv:        ## Tạo .venv và cài package editable
	test -x $(PY) || python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e libs/ben_common -e libs/ben_telemetry -e "services/gateway[dev]" -e "services/control-plane[dev]" -e "services/metering-worker[dev]" -e "libs/ben_litellm_plugins[dev]" ruff mypy openai anthropic

lint:        ## Kiểm tra code
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy

fmt:         ## Tự sửa định dạng
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

test:        ## Chạy test
	$(PY) -m pytest

test-integration: ## Test tích hợp với LiteLLM Proxy đang chạy
	$(PY) -m pytest tests/integration -v -o testpaths=tests/integration

seed-demo: ## Tạo idempotent tenant demo và virtual key dev
	$(PY) scripts/seed_demo_tenants.py

config:      ## Kiểm tra cấu hình compose
	$(COMPOSE_ALL) config --quiet

up:          ## Chạy toàn bộ (gồm observability)
	$(COMPOSE_ALL) up -d --build

up-core:     ## Chạy phần lõi
	$(COMPOSE_CORE) up -d --build

down:        ## Dừng
	$(COMPOSE_ALL) down

ps:          ## Trạng thái
	$(COMPOSE_ALL) ps

logs:        ## Xem log (make logs s=gateway)
	$(COMPOSE_ALL) logs -f --tail 100 $(s)

migrate:     ## Chạy migration schema
	$(COMPOSE_CORE) run --rm migrate

pull-model:  ## Tải model Ollama (make pull-model MODEL=qwen2.5:7b)
	$(COMPOSE_CORE) exec ollama ollama pull $(MODEL)
