set shell := ["bash", "-cu"]

default:
    @just --list

sync:
    uv sync --dev

fmt:
    uv run ruff format

lint:
    uv run ruff check

test:
    uv run pytest

news-sync args="":
    uv run python -m holocron.domain.news {{args}}

check:
    uv run ruff format --check
    uv run ruff check
    uv run pytest

env-local:
    test -f .env.local || cp .env.local.example .env.local

env-vps:
    test -f .env || cp .env.example .env

doctor:
    command -v uv
    command -v just
    docker compose version

local-up:
    ENV_FILE=.env.local docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build

local-down:
    ENV_FILE=.env.local docker compose -f docker-compose.yml -f docker-compose.local.yml down

local-logs service="dagster-webserver":
    ENV_FILE=.env.local docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f {{service}}

local-ps:
    ENV_FILE=.env.local docker compose -f docker-compose.yml -f docker-compose.local.yml ps

vps-up:
    ENV_FILE=.env docker compose up -d --build

vps-down:
    ENV_FILE=.env docker compose down

vps-logs service="dagster-webserver":
    ENV_FILE=.env docker compose logs -f {{service}}

vps-ps:
    ENV_FILE=.env docker compose ps

vps-pull:
    git pull --ff-only

deploy:
    just vps-pull
    just vps-up
