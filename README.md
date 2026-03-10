## Local development

Install `just` with your preferred package manager, then use:

```sh
just up
just test-backend
just test-frontend
just test-e2e
```

Use `just` for local workflows. [docker-compose.yml](/home/vitevue/repos/vitevue-platform/docker-compose.yml) is for reproducible local development only. Source editing, linting, formatting, and git hooks are host-side tasks; local services and manual test runs use Docker Compose.

See [development.md](/home/vitevue/repos/vitevue-platform/development.md) for the workflow details.
