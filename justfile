set shell := ["bash", "-cu"]

default:
	@just --list

up:
	docker compose up -d

down:
	docker compose down -v

logs service='':
	if [ -n "{{service}}" ]; then docker compose logs -f {{service}}; else docker compose logs -f; fi

ps:
	docker compose ps

test-backend:
	docker compose run --rm backend scripts/lifecycle/tests-start.sh

lint-backend:
	uv run --project backend ruff check backend

format-backend:
	uv run --project backend ruff format backend

test-frontend:
	docker compose run --rm --no-deps frontend sh -lc 'bun install && bun run test'

lint-frontend:
	cd frontend && bun run lint

format-frontend:
	cd frontend && bun run format

test-e2e:
	docker compose run --rm playwright bash -lc 'npm install && npm test'

test-guards:
	docker compose run --rm playwright bash -lc 'npm install && npm run test:guards'

generate-client:
	docker compose run --rm frontend sh -lc 'mkdir -p src/lib/api/generated && bunx openapi-typescript http://backend:8000/openapi.json -o src/lib/api/generated/schema.ts'
