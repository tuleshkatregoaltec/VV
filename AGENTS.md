# Repository Guidelines

## Naming
The platform name is `Vitevue`. Do not spell it as `ViteVue`.

## Project Structure & Module Organization
This repo combines a FastAPI backend, a SvelteKit frontend, and Playwright e2e coverage. Backend code lives in `backend/app`, organized by domains such as `auth`, `analytics`, `billing`, and `project`. Tests are split between `backend/tests/api`, `backend/tests/unit`, and `frontend/tests/unit`; migrations live in `backend/migrations`. Frontend app code lives in `frontend/src`, with shared code under `frontend/src/lib` and route entries under `frontend/src/routes`. Cross-app browser tests live in `e2e`, including auth setup and guard coverage.

## Stack
- Backend: FastAPI, SQLModel, Alembic, PostgreSQL, Redis, ClickHouse
- Frontend: SvelteKit, Vite, Bun, Tailwind, Biome
- Browser testing: Playwright
- Local runtime model: host-first app processes with Docker Compose for external services

## Workflow
- The canonical developer workflow is documented in [development.md](/home/vitevue/repos/vitevue-platform/development.md). Follow that file for setup, env separation, running the app, and commit checks.
- Use `.env.dev` for host app processes.
- `just up` is services-only by default.
- `just dev-backend` and `just dev-frontend` are the normal way to run the app locally.

## Commands
- `just setup`: installs host-side backend, frontend, and Playwright tooling for local commands and hooks.
- `just up`: starts the external-service Docker Compose environment.
- `just dev-backend`: runs the FastAPI backend on the host.
- `just dev-frontend`: runs the SvelteKit frontend on the host.
- `just down`: stops the environment and removes local Compose volumes.
- `just test-backend`: runs backend tests on the host.
- `just test-frontend`: runs frontend tests on the host.
- `just build-frontend`: runs the frontend production build on the host.
- `just check-all`: runs local formatting, linting, and tests across backend and frontend.
- `just test-e2e`: runs the Playwright suite on the host from `e2e/`.
- `just test-guards`: runs the mocked route-guard Playwright suite on the host from `e2e/`.
- `just lint-backend` / `just format-backend`: convenience commands for backend Ruff checks.
- `just lint-frontend` / `just format-frontend`: convenience commands for frontend lint and format checks.
- `just generate-client`: manually regenerates the frontend API client from the backend OpenAPI schema.

## Coding Style & Naming Conventions
- Frontend formatting and linting run through repo-pinned Bun scripts and Biome.
- Keep Svelte components in `PascalCase`, stores/utilities in `camelCase`, and route folders aligned with URL paths.
- For Python, follow Ruff-compatible formatting and standard FastAPI naming: `snake_case` for modules/functions and `PascalCase` for classes.
- Treat `just` targets as the canonical command surface. Hooks and docs should stay aligned with them.

## Frontend API And Query Patterns
- The generated frontend API client is types-first, not runtime-first. Use OpenAPI-generated types from `frontend/src/lib/api/generated/hey-api`, but keep using the shared runtime client in `frontend/src/lib/api/client.ts` for actual requests unless the repo pattern changes more broadly.
- For filter-heavy transaction endpoints, keep API params canonical. Prefer explicit fields like `area_min`, `area_max`, `price_min`, `price_max`, `price_per_sqm_min`, `price_per_sqm_max`, `rent_min`, and `rent_max`. Do not introduce frontend-only bucket params like `price="<500k"` into the API contract.
- Do not rebuild transaction query params inside page components. Use the shared helpers in `frontend/src/lib/utils/transactionPages.ts` so sales, rentals, exports, and filter-option requests stay aligned.
- Keep TanStack Query keys and query builders centralized in `frontend/src/lib/queries`. Add or extend key factories there rather than assembling ad hoc query keys in route components.
- Treat transaction filter-option requests as full filter-context requests. When backend filter inputs change, update both the route handlers and the shared frontend filter builders so list queries and filter-option queries stay in sync.

## Testing Guidelines
- Prefer targeted tests close to the change.
- Python tests use `test_*.py`; frontend tests use `*.test.ts`; Playwright specs use `*.spec.ts`, with unauthenticated flows ending in `.unauth.spec.ts`.
- Coverage is configured for `backend/app` with branch tracking enabled, so add tests for business logic and API changes.
- Tests are local verification steps run with `just`; pre-commit hooks are the main commit-time enforcement mechanism.
- `just test-e2e` expects local services from `just up`, the host backend, and auth to be available; it will reuse a running host frontend or start one through Playwright's `webServer` config.

## Commit & Pull Request Guidelines
- Recent history follows Conventional Commit prefixes such as `feat:` and `chore:`.
- Keep subjects short and imperative, for example `feat: add billing webhook retry handling`.
- If auth or guarded flows change, note which local backend, frontend, and Playwright checks you ran.

## Configuration & Data Notes
- Local service credentials and URLs are wired through `docker-compose.yml` and `.env.dev`.
- Docker Compose is for local external services only; it is not the production deployment model.
- The production frontend is built directly for Cloudflare Pages with injected environment variables.
- The production backend is built from `backend/Dockerfile` and deployed separately from this repo's Compose setup.
- Prefer host tooling for source-code tasks like running the app, linting, formatting, tests, and git hooks.
- Treat anything under `.docker-volumes/` and `data/` as local state, not source.
- Do not commit secrets or generated build output.

## Local Admin Notes
- The backend host startup path runs `backend/scripts/lifecycle/prestart.sh`.
- That script applies migrations and ensures the configured local auth admin user exists.
- The default local admin credentials are stored in `.env.dev` via `FIRST_SUPERUSER` and `FIRST_SUPERUSER_PASSWORD`.
