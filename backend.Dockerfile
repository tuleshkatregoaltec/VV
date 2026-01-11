FROM python:3.14-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/

COPY pyproject.toml /app/
COPY uv.lock /app/
COPY backend /app/backend


# Disable development dependencies
ENV UV_NO_DEV=1

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "-m", "backend.app.main"]