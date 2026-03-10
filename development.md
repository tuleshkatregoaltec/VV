## Development

We use `just` for all local development workflows.

Install the required local tools before using the recipes below:

- `just`
- `docker compose`
- `uv`
- `bun`
- `prek`

Docker Compose exists to give every developer a reproducible local environment from a fresh clone. It is local-development-only infrastructure, not a production deployment definition.

The source of truth is the code in the host checkout. Prefer host tooling for linting, formatting, and git hooks. Use Docker Compose for local runtime services and for manual test execution when those tests depend on the running stack.

Key commands:

```sh
just up
just test-backend
just test-frontend
just test-e2e
```

Backend lifecycle is handled by:

- `backend/scripts/lifecycle/prestart.sh`
- `backend/scripts/lifecycle/tests-start.sh`

Git hooks use Prek against the repo's [`.pre-commit-config.yaml`](/home/vitevue/repos/vitevue-platform/.pre-commit-config.yaml). Install and enable it with:

```sh
uv tool install prek
prek install
```

Hook policy:

- Hooks should stay lightweight and host-driven.
- Linting and formatting belong in hooks.
- Tests do not belong in hooks.
- Hooks should not require Docker Compose to run.

Test policy:

- Tests are run manually during local development with `just`.
- Failing tests are a local verification signal, not a CI gate in this repo today.
- Keep the suites targeted and useful, but do not design the workflow around mandatory CI execution.

Deployment policy:

- The frontend production build is for Cloudflare Pages with environment variables injected by that platform.
- The backend production image is built from `backend/Dockerfile`.
- Managed production services such as databases, caches, and object storage are external and are not provisioned by this repo.
- The only GitHub Action we rely on is backend Docker build/publish verification.

The generated API client is manual for now. Run `just generate-client` after changing backend routes or schemas.

Playwright runs in its own container using the tooling defined under `e2e/`.
