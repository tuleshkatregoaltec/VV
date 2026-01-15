FROM python:3.14-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/

COPY backend /app/backend

# Disable development dependencies
ENV UV_NO_DEV=1

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app/backend
RUN uv sync --locked && apt-get update && apt-get install curl -y

CMD ["uv", "run", "gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker"]