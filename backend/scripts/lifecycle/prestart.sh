#!/usr/bin/env sh

set -eu

uv run alembic upgrade head
uv run python -m scripts.admin.create_auth_admin_user
