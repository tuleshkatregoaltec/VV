set shell := ["bash", "-cu"]

default:
	@just --list

setup:
	cd frontend && bun install
	cd e2e && bun install && bunx --bun playwright install chromium
	cd backend && uv sync

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
