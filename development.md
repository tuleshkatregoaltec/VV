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

The source of truth is the code in the host checkout. Frontend, backend, and Playwright run on the host by default. Use Docker Compose for external services only.

Environment file:

- [`.env.dev`](/home/vitevue/repos/vitevue-platform/.env.dev) is the local runtime config for host app processes.

## Setup

Fresh clone quick start:

```sh
just setup
uv tool install prek
prek install
```

What these do:

- `just setup` installs frontend and e2e dependencies with Bun, installs the local Playwright Chromium browser, syncs the backend environment with `uv`, starts the local external services stack, applies migrations, and seeds the local bootstrap admin with an active organization and subscription
- `prek install` enables the repo hooks locally

## Running The App

Run the app on the host:

```sh
just dev-backend
just dev-frontend
```

Or start the full local stack in one command:

```sh
just dev
```

What this does:

- `just dev` starts the external services with Docker Compose, then runs the backend and frontend together on the host
- `just dev-app` runs the backend and frontend together on the host when services are already running
- `just up` remains services-only for cases where you only want the dependency stack

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
just dev
just dev-app
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

`just setup` prepares host-side backend, frontend, and Playwright tooling. It does not start Docker Compose.

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
- Make sure the backend is running with `just dev-backend`.
- Run `just check-all`.
- Run `just test-e2e` if your change touches auth flows, route guards, or browser-critical UI behavior.
- Commits are blocked when the configured Prek hooks fail.

## Cross-Platform Notes

Cross-platform note:

- The host-first workflow is the supported way to develop on Linux and macOS.
- Docker Compose is the supported way to boot local dependencies on Linux and macOS.
- Playwright runs on the host and targets the local app URLs directly.

### macOS Prerequisites

Install prerequisites via [Homebrew](https://brew.sh). If Homebrew is not installed:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Install Xcode command-line tools (required for native build dependencies):

```sh
xcode-select --install
```

Install the runtime prerequisites:

```sh
brew install just
brew install uv
brew install oven-sh/bun/bun
```

Install Docker Desktop from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop). Docker Compose is bundled with Docker Desktop. **Docker Desktop must be open and running before `just up` or `just dev`.**

After all prerequisites are installed, run the standard setup:

```sh
just setup
uv tool install prek
prek install
```

Note: follow any post-install instructions that `brew` prints for `uv` and `bun` (they may require adding entries to your shell profile `~/.zshrc`).

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
