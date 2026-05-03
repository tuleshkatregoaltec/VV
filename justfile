set shell := ["bash", "-cu"]

default:
    @just --list

sync:
    uv sync --dev

fmt:
    uv run ruff format

test:
    uv run pytest

check:
    uv run ruff format --check
    uv run ruff check
    uv run pytest

news-sync args="":
    uv run python -m holocron.domain.news {{args}}

env target="prod" +args='':
    @case "{{target}}" in \
      prod) bash scripts/pull-bitwarden-env.sh {{args}} ;; \
      prod-manual) test -f .env || cp .env.example .env ;; \
      r2) if [[ -n "$${BWS_ACCESS_TOKEN:-}" ]]; then bash scripts/pull-bitwarden-env.sh --env-file .env.r2-test --raw-only {{args}}; else test -f .env.r2-test || cp .env.r2.example .env.r2-test; fi ;; \
      local) test -f .env.local || cp .env.local.example .env.local ;; \
      *) echo "Unknown env target: {{target}}. Use prod, prod-manual, r2, or local." >&2; exit 2 ;; \
    esac

doctor target="prod" +args='':
    @case "{{target}}" in \
      prod) just _compose prod run --build --rm --no-deps dagster-webserver python -m holocron.platform.doctor --env-file /dev/null --check-connections {{args}} ;; \
      r2) just _compose r2 up -d postgres; just _compose r2 run --build --rm --no-deps dagster-webserver python -m holocron.platform.doctor --env-file /dev/null --raw-only --check-connections {{args}} ;; \
      local) command -v uv; command -v just; docker compose version; just _compose local config --services >/dev/null ;; \
      host) command -v uv; command -v just; docker compose version ;; \
      *) echo "Unknown doctor target: {{target}}. Use prod, r2, local, or host." >&2; exit 2 ;; \
    esac

up target="prod":
    @case "{{target}}" in \
      prod) just doctor prod; just _compose prod up -d --build ;; \
      r2) just doctor r2; just _compose r2 up -d --build ;; \
      local) just _compose local up -d --build ;; \
      *) echo "Unknown up target: {{target}}. Use prod, r2, or local." >&2; exit 2 ;; \
    esac

down target="prod":
    @just _compose {{target}} down

logs target="prod" service="dagster-webserver":
    @just _compose {{target}} logs -f {{service}}

ps target="prod":
    @just _compose {{target}} ps

deploy:
    git pull --ff-only
    just up prod

_compose target +args:
    @case "{{target}}" in \
      prod) ENV_FILE=.env docker compose {{args}} ;; \
      r2) ENV_FILE=.env.r2-test docker compose -f docker-compose.yml -f docker-compose.raw-test.yml {{args}} ;; \
      local) ENV_FILE=.env.local docker compose -f docker-compose.yml -f docker-compose.local.yml {{args}} ;; \
      *) echo "Unknown compose target: {{target}}. Use prod, r2, or local." >&2; exit 2 ;; \
    esac
