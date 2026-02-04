FROM python:3.14-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/

WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock /app/backend/

RUN uv sync

COPY backend /app/backend

RUN apt-get update && apt-get install curl -y && rm -rf /var/lib/apt/lists/*

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
