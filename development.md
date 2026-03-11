## Development

We use `just` for all local development workflows.

Minimum runtime prerequisites for a fresh clone:

- `just`
- `docker compose`
- `uv`
- `bun`

Optional host-side developer tooling:

- `prek`

Docker Compose exists to give every developer a reproducible local services environment from a fresh clone. It is local-development-only infrastructure, not a production deployment definition.

The source of truth is the code in the host checkout. Frontend and backend run on the host by default. Use Docker Compose for external services and for Playwright.

Environment file:

- [`.env.dev`](/home/vitevue/repos/vitevue-platform/.env.dev) is the local runtime config for host app processes.

## Setup

Fresh clone quick start:

```sh
just setup
just up
uv tool install prek
prek install
```

What these do:

- `just setup` installs frontend dependencies with Bun and syncs the backend environment with `uv`
- `just up` starts the external services stack
- `prek install` enables the repo hooks locally

## Running The App

Run the app on the host:

```sh
just dev-backend
just dev-frontend
```

Main local endpoints:

- frontend: `http://localhost:5173`
- backend API: `http://localhost:8000`
- auth: `http://localhost:9999`
- mail UI: `http://localhost:9000`
- MinIO console: `http://localhost:9003`

Local admin bootstrap:

- `just dev-backend` runs `backend/scripts/lifecycle/prestart.sh` before starting Uvicorn
- that script applies migrations and ensures the local bootstrap superuser exists
- the default local bootstrap superuser credentials live in [`.env.dev`](/home/vitevue/repos/vitevue-platform/.env.dev) via `FIRST_SUPERUSER` and `FIRST_SUPERUSER_PASSWORD`

## Common Commands

Common follow-up commands:

```sh
just check-all
just test-backend
just test-frontend
just lint-backend
just lint-frontend
just format-backend
just format-frontend
just build-frontend
just test-e2e
just test-guards
```

`just setup` prepares host-side backend and frontend tooling. It does not start Docker Compose.

Backend lifecycle is handled by:

- `backend/scripts/lifecycle/prestart.sh`
- `backend/scripts/lifecycle/tests-start.sh`

## Environment Notes

- Keep local runtime URLs and ports in [`.env.dev`](/home/vitevue/repos/vitevue-platform/.env.dev).
- The backend loads `.env.dev` by default in host mode.

## Git Hooks

Git hooks use Prek against the repo's [`.pre-commit-config.yaml`](/home/vitevue/repos/vitevue-platform/.pre-commit-config.yaml). Install and enable it with:

```sh
uv tool install prek
prek install
```

By default, `prek` runs on staged files during `git commit`. To run the configured hooks across the whole repo manually, use:

```sh
prek run --all-files
```

If host `uv` commands fail with cache permission errors, repair the ownership of `~/.cache/uv` and avoid running `uv` with `sudo`.

Hook policy:

- Hooks should stay lightweight and host-driven.
- Hooks should call the same underlying local tools used by the documented `just` commands.
- Linting belongs in hooks.
- Formatting may be run manually before commit via `just format-backend` and `just format-frontend`.
- Tests and builds remain manual local commands.
- Hooks should not require Docker Compose to run.
- Hooks should validate staged files only and should not rewrite files during `git commit`.

## Before Committing

Before committing:

- Make sure services are up with `just up`.
- Run `just check-all`.
- Run `just test-e2e` if your change touches auth flows, route guards, or browser-critical UI behavior.
- Commits are blocked when the configured Prek hooks fail.

## Cross-Platform Notes

Cross-platform note:

- The host-first workflow is the supported way to develop on Linux and macOS.
- Docker Compose is the supported way to boot local dependencies on Linux and macOS.
- The Playwright container targets the host apps through `host.docker.internal`, with a host-gateway mapping for Linux.

## Checks And Tests

Test policy:

- Tests, linting, and formatting are run locally with `just`.
- Pre-commit hooks are the primary enforcement mechanism before commit.
- Failing checks are a local verification signal, not a CI gate in this repo today.
- Keep the suites targeted and useful.

## Deployment Notes

Deployment policy:

- The frontend production build is for Cloudflare Pages with environment variables injected by that platform.
- The backend production image is built from `backend/Dockerfile`.
- Managed production services such as databases, caches, and object storage are external and are not provisioned by this repo.

The generated API client is manual for now. Run `just generate-client` after changing backend routes or schemas.

Playwright runs in its own container using the tooling defined under `e2e/`.
