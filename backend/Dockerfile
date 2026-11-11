FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/

COPY backend /app/backend

ENV UV_NO_DEV=1

WORKDIR /app/backend
RUN uv sync --locked && apt-get update && apt-get install -y --no-install-recommends curl libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-noto-core && rm -rf /var/lib/apt/lists/*

CMD ["uv", "run", "gunicorn", "app.main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
