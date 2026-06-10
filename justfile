set shell := ["bash", "-cu"]

default:
	@just --list

setup:
	cd frontend && bun install
	cd e2e && bun install && bunx --bun playwright install chromium
	cd backend && uv sync
	just up
	set -a && source .env.dev && set +a && cd backend && uv run alembic upgrade head && uv run python -m scripts.admin.create_auth_admin_user && uv run python -m scripts.admin.bootstrap_local_admin_state

up:
	docker compose up --build -d postgres auth-db-init auth inbucket clickhouse redis minio minio-setup

down:
	docker compose down -v

logs service='':
	if [ -n "{{service}}" ]; then docker compose logs -f {{service}}; else docker compose logs -f; fi

ps:
	docker compose ps

dev-backend:
	set -a && source .env.dev && set +a && cd backend && uv sync && scripts/lifecycle/prestart.sh && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

dev-frontend:
	set -a && source .env.dev && set +a && cd frontend && bun install && bun run dev -- --host 0.0.0.0 --port 5173

dev-app:
	set -a && source .env.dev && set +a && \
		for port in 8000 5173; do \
			pid=$(lsof -t -nP -iTCP:$port -sTCP:LISTEN 2>/dev/null | head -n 1); \
			if [ -n "$pid" ]; then \
				echo "Port $port is already in use by PID $pid:"; \
				ps -p "$pid" -o pid=,ppid=,cmd=; \
				echo "Stop the existing process or use the running app directly."; \
				exit 1; \
			fi; \
		done; \
		(cd backend && uv sync && scripts/lifecycle/prestart.sh && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload) & \
		backend_pid=$!; \
		(cd frontend && bun install && bun run dev -- --host 0.0.0.0 --port 5173) & \
		frontend_pid=$!; \
		trap 'kill $backend_pid $frontend_pid 2>/dev/null || true' EXIT INT TERM; \
		wait -n $backend_pid $frontend_pid; \
		exit_code=$?; \
		kill $backend_pid $frontend_pid 2>/dev/null || true; \
		wait $backend_pid $frontend_pid 2>/dev/null || true; \
		exit $exit_code

dev:
	just up
	just dev-app

test-backend:
	set -a && source .env.dev && set +a && cd backend && scripts/lifecycle/tests-start.sh

lint-backend:
	uv run --project backend ruff format --check backend
	uv run --project backend ruff check backend

format-backend:
	uv run --project backend ruff format backend
	uv run --project backend ruff check --fix backend

test-frontend:
	set -a && source .env.dev && set +a && cd frontend && bun run test

build-frontend:
	set -a && source .env.dev && set +a && cd frontend && bun run build

lint-frontend:
	cd frontend && bun run lint

format-frontend:
	cd frontend && bun run format

check-all:
	just format-backend
	just format-frontend
	just lint-backend
	just lint-frontend
	just test-backend
	just test-frontend

test-e2e:
	set -a && source .env.dev && set +a && cd e2e && bun run test

test-guards:
	set -a && source .env.dev && set +a && cd e2e && bun run test:guards

generate-client:
	./scripts/generate-client.sh

load-clickhouse-local:
	set -a && source .env.dev && set +a && cd backend && uv run scripts/data/insert/load_local_clickhouse.py && uv run python -m scripts.clickhouse.build_fact_tables

build-clickhouse-facts:
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.clickhouse.build_fact_tables

import-mashrooi-radar-demo:
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.radar.import_mashrooi_coordinates_demo
