# Repository Guidelines

## Naming
The platform name is `Vitevue`. Do not spell it as `ViteVue`.

## Project Structure & Module Organization
This repo combines a FastAPI backend, a SvelteKit frontend, and Playwright e2e coverage. Backend code lives in `backend/app`, organized by domains such as `auth`, `analytics`, `billing`, and `project`. Tests are split between `backend/tests/api`, `backend/tests/unit`, and `frontend/tests/unit`; migrations live in `backend/migrations`. Frontend app code lives in `frontend/src`, with shared code under `frontend/src/lib` and route entries under `frontend/src/routes`. Cross-app browser tests live in `e2e`, including auth setup and guard coverage.

## Build, Test, and Development Commands
- `just up`: starts the local Docker Compose environment.
- `just down`: stops the environment and removes local Compose volumes.
- `just test-backend`: runs backend tests through the backend lifecycle script.
- `just test-frontend`: runs frontend tests in the frontend container.
- `just test-e2e`: runs Playwright in the dedicated Playwright container.
- `just test-guards`: runs the mocked route-guard Playwright suite.
- `just lint-backend` / `just format-backend`: convenience commands for backend Ruff checks.
- `just lint-frontend` / `just format-frontend`: convenience commands for frontend lint and format checks.
- `just generate-client`: manually regenerates the frontend API client from the backend OpenAPI schema.

## Coding Style & Naming Conventions
Frontend formatting is enforced by Prettier and ESLint. Prettier uses tabs, single quotes, no trailing commas, and `printWidth: 100`. Keep Svelte components in `PascalCase`, stores/utilities in `camelCase`, and route folders aligned with URL paths. For Python, follow Ruff-compatible formatting and standard FastAPI naming: `snake_case` for modules/functions and `PascalCase` for classes.

## Testing Guidelines
Prefer targeted tests close to the change. Python tests use `test_*.py`; frontend tests use `*.test.ts`; Playwright specs use `*.spec.ts`, with unauthenticated flows ending in `.unauth.spec.ts`. Coverage is configured for `backend/app` with branch tracking enabled, so add tests for business logic and API changes. Tests are for local development verification and are run manually with `just`; they are not part of git hooks and are not treated as CI blockers.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commit prefixes such as `feat:` and `chore:`. Keep subjects short and imperative, for example `feat: add billing webhook retry handling`. Pull requests should explain user-visible impact, call out schema or config changes, link the issue when available, and include screenshots for UI updates. If auth or guarded flows change, note which local backend, Vitest, and Playwright checks you ran.

## Configuration & Data Notes
Local service credentials and URLs are wired through `docker-compose.yml` and `.env.dev`. Docker Compose is for the reproducible local development environment only; it is not the production deployment model. The production frontend is built directly for Cloudflare Pages with injected environment variables, and the production backend is built from `backend/Dockerfile` and deployed separately from this repo's Compose setup. Prefer host tooling for source-code tasks like linting, formatting, and git hooks. Use Docker Compose for local services and for manual local test execution. Treat anything under `.docker-volumes/` and `data/` as local state, not source, including Playwright auth/report/result artifacts. Do not commit secrets or generated build output.
Required local developer tooling is `just`, `docker compose`, `uv`, `bun`, and `prek`.
