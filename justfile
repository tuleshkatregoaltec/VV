set shell := ["bash", "-cu"]
set positional-arguments

default:
	@just --list

setup:
	cd frontend && bun install
	cd e2e && bun install && bunx --bun playwright install chromium
	cd backend && uv sync
	just up
	set -a && source .env.dev && set +a && cd backend && uv run alembic upgrade head && uv run python -m scripts.admin.create_auth_admin_user && uv run python -m scripts.admin.bootstrap_local_admin_state

up:
	docker compose -f docker-compose.dev.yml up --build -d

down:
	docker compose -f docker-compose.dev.yml down -v

logs service='':
	if [ -n "{{service}}" ]; then docker compose -f docker-compose.dev.yml logs -f {{service}}; else docker compose -f docker-compose.dev.yml logs -f; fi

ps:
	docker compose -f docker-compose.dev.yml ps

dev-backend:
	#!/usr/bin/env bash
	set -euo pipefail
	set -a
	source .env.dev
	set +a
	cd backend
	uv sync
	scripts/lifecycle/prestart.sh
	uv run python -m app.crm.import_worker &
	worker_pid=$!
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload &
	api_pid=$!
	cleanup() { kill "$api_pid" "$worker_pid" 2>/dev/null || true; wait "$api_pid" "$worker_pid" 2>/dev/null || true; }
	trap cleanup EXIT INT TERM
	while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do sleep 1; done
	if ! kill -0 "$api_pid" 2>/dev/null; then wait "$api_pid"; else wait "$worker_pid"; fi

dev-frontend:
	set -a && source .env.dev && set +a && cd frontend && bun install && bun run dev -- --host 0.0.0.0 --port 5173

dev-app:
	#!/usr/bin/env bash
	set -euo pipefail
	set -a
	source .env.dev
	set +a
	for port in 8002 5173; do
		pid=$(lsof -t -nP -iTCP:$port -sTCP:LISTEN 2>/dev/null | head -n 1 || true)
		if [ -n "$pid" ]; then
			echo "Port $port is already in use by PID $pid:"
			ps -p "$pid" -o pid=,ppid=,cmd=
			echo "Stop the existing process or use the running app directly."
			exit 1
		fi
	done
	(
		cd backend
		uv sync
		scripts/lifecycle/prestart.sh
		uv run python -m app.crm.import_worker &
		worker_pid=$!
		uv run uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload &
		api_pid=$!
		cleanup_backend() { kill "$api_pid" "$worker_pid" 2>/dev/null || true; wait "$api_pid" "$worker_pid" 2>/dev/null || true; }
		trap cleanup_backend EXIT INT TERM
		while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do sleep 1; done
		if ! kill -0 "$api_pid" 2>/dev/null; then wait "$api_pid"; else wait "$worker_pid"; fi
	) &
	backend_pid=$!
	(cd frontend && bun install && bun run dev -- --host 0.0.0.0 --port 5173) &
	frontend_pid=$!
	cleanup() { kill "$backend_pid" "$frontend_pid" 2>/dev/null || true; wait "$backend_pid" "$frontend_pid" 2>/dev/null || true; }
	trap cleanup EXIT INT TERM
	while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do sleep 1; done
	if ! kill -0 "$backend_pid" 2>/dev/null; then wait "$backend_pid"; else wait "$frontend_pid"; fi

dev:
	just up
	just dev-app

env:
	bash scripts/pull-bitwarden-env.sh

init:
	docker compose --profile init run --rm auth-db-init

migrate:
	docker compose run --rm --no-deps backend uv run alembic upgrade head

deploy:
	docker compose pull backend
	just migrate
	docker compose up -d --no-build backend auth redis

test-backend *args:
	set -a && source .env.dev && set +a && cd backend && scripts/lifecycle/tests-start.sh "$@"

format-backend:
	uv run --project backend ruff format backend
	uv run --project backend ruff check --fix backend

test-frontend:
	set -a && source .env.dev && set +a && cd frontend && bun run test

build-frontend:
	set -a && source .env.dev && set +a && cd frontend && bun run build

# Explicit public endpoints for the isolated pilot; do not source local credentials.
build-pilot-frontend api_url auth_url publishable_key="":
	cd frontend && PUBLIC_API_BASE_URL="$1" PUBLIC_AUTH_BASE_URL="$2" PUBLIC_AUTH_PUBLISHABLE_KEY="$3" PUBLIC_CRM_PRESENTATION_MODE=true PUBLIC_POSTHOG_KEY= PUBLIC_POSTHOG_HOST= bun run build

# Reuse restored accounts and saved ownership results without full reassessment.
dev-pilot-backend:
	set -a && source .env.dev && set +a && cd backend && uv run alembic upgrade head && CRM_INBOUND_OWNER_ENRICHMENT_MODE=stored CRM_MAX_EXPENSIVE_REQUESTS=1 CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG=1 uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# Status is local-only; send-test sends one approved template to the configured test recipient.
whatsapp-demo command='status':
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.whatsapp_demo "$1"

# Durable single-number pilot automation; other senders cannot acquire this identity.
whatsapp-worker:
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.whatsapp_worker

format-frontend:
	cd frontend && bun run format

# Read-only frontend checks: Biome lint/format check and Svelte/TypeScript diagnostics.
lint-frontend:
	cd frontend && bun run lint

check-frontend:
	cd frontend && bun run check

check-all:
	just format-backend
	just format-frontend
	just test-backend
	just test-frontend

test-e2e *args:
	set -a && source .env.dev && set +a && cd e2e && bun run test "$@"

test-guards:
	set -a && source .env.dev && set +a && cd e2e && bun run test:guards

generate-client:
	./scripts/generate-client.sh

load-clickhouse-local:
	set -a && source .env.dev && set +a && cd backend && uv run scripts/data/insert/load_local_clickhouse.py && uv run python -m scripts.clickhouse.build_fact_tables

build-clickhouse-facts:
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.clickhouse.build_fact_tables

holocron +args='':
	@cd holocron && just {{args}}

# Read-only checks and explicitly isolated integration suites.
lint-backend:
	uv run --project backend ruff check backend
	uv run --project backend ruff format --check backend

test-backend-postgres *args:
	set -a && source .env.dev && set +a && cd backend && uv run pytest tests/integration/postgres "$@"

test-backend-clickhouse *args:
	set -a && source .env.dev && set +a && cd backend && uv run pytest tests/integration/clickhouse "$@"

test-backend-infrastructure *args:
	set -a && source .env.dev && set +a && cd backend && uv run pytest tests/integration/infrastructure "$@"

# Read-only AI capability discovery; does not call model providers or upload data.
ai-inventory:
	cd backend && uv run python -m scripts.evaluations.market_ai inventory

ai-benchmark:
	cd backend && uv run python -m scripts.evaluations.market_ai dataset

crm-ai-benchmark:
	cd backend && uv run python -m scripts.evaluations.crm_assistant

# CRM Assistant offline checks: cases, CRM-only tools, scoring, opt-in gates. No database, model or network.
crm-eval-offline *args:
	set -a && source backend/tests/evaluation/offline.env && set +a && cd backend && uv run pytest tests/evaluation/test_crm_dataset.py tests/evaluation/test_crm_scoring.py "$@"

# Every CRM case's probe on a disposable LOCAL database (TEST_POSTGRES_URL); dummy settings, never .env.dev; no model.
crm-eval-db *args:
	set -a && source backend/tests/evaluation/offline.env && set +a && test -n "${TEST_POSTGRES_URL:-}" || { echo "Set TEST_POSTGRES_URL to a local PostgreSQL" >&2; exit 2; }; cd backend && uv run pytest tests/integration/postgres/test_crm_assistant_evaluation.py "$@"

# Preview by default. --live also needs CRM_EVAL_ALLOW_MODEL_CALLS=1 and a local CRM_EVAL_POSTGRES_URL (paid model calls).
crm-eval-live *args:
	cd backend && POSTGRES_URL="${CRM_EVAL_POSTGRES_URL:-}" uv run python -m scripts.evaluations.crm_assistant live "$@"

test-evaluation *args:
	just test-backend tests/evaluation {{args}}

# Explicit live model execution, private evidence, local authenticated application.
ai-evaluate *args:
	cd backend && uv run python -m scripts.evaluations.market_ai run {{args}}

# Opt-in isolated fixture creation/verification/cleanup; never call models or create auth users.
ai-evaluation-snapshot *args:
	cd backend && uv run python -m scripts.evaluations.market_ai.fixture_snapshot {{args}}

# Preview by default; --live compares models using synthetic tools, never live records/actions.
ai-model-trial *args:
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.evaluations.market_ai.model_trial {{args}}

# Local trace assessment and comparison; never call models or export evidence.
ai-assess *args:
	cd backend && uv run python -m scripts.evaluations.market_ai assess {{args}}

ai-compare *args:
	cd backend && uv run python -m scripts.evaluations.market_ai compare {{args}}

# Preview by default. --upload explicitly sends only allowlisted metadata to LangSmith.
ai-export *args:
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.evaluations.market_ai export {{args}}

# Read-only proposals from retained DXBI report evidence; no warehouse writes.
audit-dxbi-name-repairs *args:
	set -a && source .env.dev && set +a && PYTHONPATH=holocron uv run --project holocron python holocron/scripts/audit_dxbi_name_repairs.py {{args}}

# Read-only controlled comparison of the one explicitly authorized owner workbook.
compare-owner-import *args:
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.crm.compare_owner_import "$@"

# Evaluate a reproducible 20-file owner sample against read-only DXBI evidence.
evaluate-owner-corpus *args:
	set -a && source .env.dev && set +a && cd backend && uv run python -m scripts.crm.evaluate_owner_corpus "$@"

# Offline owner-recovery experiment handoff; no live importer writes.
owner-recovery *args:
	cd backend && uv run python -m scripts.crm.owner_recovery_experiment.cli "$@"

# Export only the fixed experiment's unresolved rows, including original columns.
export-unresolved-owner-rows *args:
	cd backend && uv run python -m scripts.crm.export_unresolved_owner_rows "$@"
# Run one resource-bounded import at a time, separate from the HTTP process.
crm-import-worker *args:
	set -a && source .env.dev && set +a && cd backend && uv run python -m app.crm.import_worker {{args}}

# Sample-only enterprise preview; no backend, credentials or service startup required.
demo-assistant:
	cd frontend && bun run dev -- --host 127.0.0.1 --port 5173
