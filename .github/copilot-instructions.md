# Repository Guidelines

## Project Structure & Module Organization
This repo combines a FastAPI backend, a SvelteKit frontend, and Playwright e2e coverage. Backend code lives in `backend/app`, organized by domains such as `auth`, `analytics`, `billing`, and `project`. Tests are split between `backend/tests/api`, `backend/tests/unit`, and `frontend/tests/unit`; migrations live in `backend/migrations`. Frontend app code lives in `frontend/src`, with shared code under `frontend/src/lib` and route entries under `frontend/src/routes`. Cross-app browser tests live in `e2e`, including auth setup and guard coverage.

## Stack
- Backend: FastAPI, SQLModel, Alembic, PostgreSQL, Redis, ClickHouse
- Frontend: SvelteKit, Vite, Bun, Tailwind, Biome
- Browser testing: Playwright
- Local runtime model: host-first app processes with Docker Compose for external services

## Platform Notes
- This repo is developed on both Linux and macOS.
- On macOS, prerequisites (`just`, `uv`, `bun`) are installed via Homebrew. Docker Compose is bundled with Docker Desktop, which must be running before any `just up` or `just dev` command.
- Package manager for macOS: `brew`. Do not suggest `apt` or `snap` commands to macOS users.
- Default shell on macOS is `zsh`. The justfile uses `bash` explicitly so shell compatibility is not an issue.
- When suggesting install steps on macOS, use `brew install <package>` for CLI tools and refer to Docker Desktop for the container runtime.

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
- Keep domain-specific ClickHouse SQL in the owning domain module such as `backend/app/analytics`; reserve `backend/app/clickhouse/queries.py` for shared cross-domain query helpers.

## Feature Development Standards

When building a new feature, follow these layer-by-layer conventions. Each layer has a specific responsibility — do not skip or merge layers.

### Backend Layer Order

1. **`backend/app/{domain}/models.py`** — Pydantic request/response schemas. Define all input and output types here. Do not define schemas inline in the router.
2. **`backend/app/{domain}/service.py`** — Business logic and data access. Queries are written inline here for most domains. Raise HTTPExceptions here; keep router handlers thin.
3. **`backend/app/{domain}/router.py`** — FastAPI endpoints. Call service functions, apply auth guards (`Depends(require_auth)`, `Depends(require_active_subscription)`), return typed responses.
4. **`backend/app/main.py`** — Register the new router with `app.include_router(...)`, matching the existing import/registration pattern.
5. **`backend/migrations/`** — Add an Alembic migration if the feature introduces new PostgreSQL tables. Run `uv run alembic revision --autogenerate -m "..."` inside `backend/`.

Only extract a separate **`queries.py`** when the domain has a large volume of complex SQL (as in `analytics` and `feasibility`). For most features, keep queries inline in `service.py`.

### Frontend Layer Order

1. **Run `just generate-client`** after any backend schema change to regenerate `frontend/src/lib/api/generated/hey-api/types.gen.ts`.
2. **`frontend/src/lib/api/{feature}.ts`** — Typed API functions using the shared `client` from `client.ts`. Export a named object (e.g. `export const analytics = { ... }`). Import response types from `generated/hey-api/types.gen.ts`.
3. **`frontend/src/lib/queries/{feature}.ts`** — TanStack Query key factories and query config builders. Follow the `{feature}Keys` / `{feature}Queries` naming pattern. Add all `queryKey` definitions here — never assemble ad-hoc keys in components or pages.
4. **`frontend/src/lib/stores/{feature}.svelte.ts`** — Only add a store if the feature has complex cross-component state (e.g. multi-step flows, derived state). Simple features that only fetch data do not need a store.
5. **`frontend/src/lib/components/{feature}/`** — Feature components in `PascalCase`. Subdivide into subfolders if the feature has distinct areas (e.g. `sheets/`, `research/`). Components bind to TanStack Query via `createQuery`; they do not call the API directly.
6. **`frontend/src/routes/{feature}/+page.svelte`** — Route entry point. Load data via `createQuery` using builders from the query layer. Keep route files thin — delegate rendering to components.

### Tests

- Backend route tests: `backend/tests/api/test_{feature}_router.py`
- Backend logic tests: `backend/tests/unit/test_{feature}_service.py`
- Frontend unit tests: `frontend/tests/unit/{feature}.test.ts`
- E2e browser tests: `e2e/{feature}.spec.ts` (unauthenticated variants: `{feature}.unauth.spec.ts`)

### Common Mistakes To Avoid

- Do not make API calls directly from route pages or components — always go through the query layer.
- Do not assemble `queryKey` arrays ad-hoc inside components — define them in `queries/{feature}.ts`.
- Do not put domain-specific ClickHouse SQL in `backend/app/clickhouse/queries.py` — that file is for shared cross-domain helpers only. Domain SQL belongs in `backend/app/{domain}/service.py` (or `queries.py` for large domains).
- Do not put business logic in router handlers — it belongs in `service.py`.
- Do not forget to run `just generate-client` after changing backend schemas; stale generated types cause type errors across the frontend.

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
