#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"
FORCE=0
BWS_IMAGE="${BWS_IMAGE:-ghcr.io/bitwarden/bws}"
# vitevue-prod project — not a secret
BWS_PROJECT_ID="${BWS_PROJECT_ID:-0848f0fb-cb6e-44fe-89f5-b3de00d7f090}"

usage() {
  cat <<'USAGE'
Usage: scripts/pull-bitwarden-env.sh [--env-file PATH] [--project-id UUID] [--force]

Pull platform environment variables from Bitwarden Secrets Manager and write
them to .env. Requires:

  BWS_ACCESS_TOKEN   Bitwarden Secrets Manager machine account access token
  BWS_PROJECT_ID     Bitwarden Secrets Manager project id, unless --project-id is passed

The script uses the official bws Docker image, so the host only needs Docker.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="${2:?--env-file requires a path}"
      shift 2
      ;;
    --project-id)
      BWS_PROJECT_ID="${2:?--project-id requires a project id}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${BWS_ACCESS_TOKEN:-}" ]]; then
  echo "BWS_ACCESS_TOKEN is required." >&2
  exit 2
fi

if [[ -z "${BWS_PROJECT_ID:-}" ]]; then
  echo "BWS_PROJECT_ID is required. Pass --project-id or export BWS_PROJECT_ID." >&2
  exit 2
fi

if [[ -e "$ENV_FILE" && "$FORCE" != "1" ]]; then
  echo "$ENV_FILE already exists. Re-run with --force to overwrite it." >&2
  exit 2
fi

TMP_FILE="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
trap 'rm -f "$TMP_FILE"' EXIT

docker run --rm \
  -e BWS_ACCESS_TOKEN \
  "$BWS_IMAGE" \
  secret list "$BWS_PROJECT_ID" --output env --color no > "$TMP_FILE"

if [[ ! -s "$TMP_FILE" ]]; then
  echo "Bitwarden returned no secrets for project $BWS_PROJECT_ID." >&2
  exit 1
fi

if grep -q "commented-out due to a problematic key name" "$TMP_FILE"; then
  echo "Bitwarden reported one or more non-POSIX secret keys. Fix the key names first." >&2
  exit 1
fi

REQUIRED_KEYS=(
  POSTGRES_URL
  REDIS_PASSWORD
  SESSION_SECRET
  SERVICE_API_KEY
  AUTH_SERVICE_ROLE_KEY
  GOTRUE_JWT_SECRET
  GOTRUE_DB_DATABASE_URL
  API_EXTERNAL_URL
  GOTRUE_SMTP_HOST
  GOTRUE_SMTP_USER
  GOTRUE_SMTP_PASS
  GOTRUE_SMTP_ADMIN_EMAIL
  FRONTEND_URL
  PUBLIC_API_BASE_URL
  OBJECT_STORAGE_ENDPOINT_URL
  OBJECT_STORAGE_ACCESS_KEY_ID
  OBJECT_STORAGE_SECRET_ACCESS_KEY
  OBJECT_STORAGE_BUCKET
  STRIPE_SECRET_KEY
  STRIPE_WEBHOOK_SECRET
  OPENROUTER_API_KEY
  POSTGRES_USER
  POSTGRES_PASSWORD
  AUTH_DB_PASSWORD
)

EXPECTED_KEYS=(
  "${REQUIRED_KEYS[@]}"
  STRIPE_PRICE_ID_TIER1
  STRIPE_PRICE_ID_TIER2
  POSTHOG_API_KEY
  HONEYBADGER_API_KEY
  CLICKHOUSE_PASSWORD
  OBJECT_STORAGE_PUBLIC_URL_BASE
  FRONTEND_SUCCESS_URL
  FRONTEND_CANCEL_URL
)

MISSING_REQUIRED=()
for key in "${REQUIRED_KEYS[@]}"; do
  if ! grep -Eq "^${key}=" "$TMP_FILE" || grep -Eq "^${key}=\"\"$" "$TMP_FILE"; then
    MISSING_REQUIRED+=("$key")
  fi
done

# Treat TO_BE_SET as missing
while IFS= read -r line; do
  key="${line%%=*}"
  if grep -Eq "^${key}=\"TO_BE_SET\"$" "$TMP_FILE"; then
    MISSING_REQUIRED+=("$key (still set to TO_BE_SET)")
  fi
done < <(grep -E "^[A-Z_]+=" "$TMP_FILE")

if (( ${#MISSING_REQUIRED[@]} > 0 )); then
  printf 'Missing or unfilled required Bitwarden secrets:\n' >&2
  printf '  %s\n' "${MISSING_REQUIRED[@]}" >&2
  exit 1
fi

MISSING_EXPECTED=()
for key in "${EXPECTED_KEYS[@]}"; do
  if ! grep -Eq "^${key}=" "$TMP_FILE"; then
    MISSING_EXPECTED+=("$key")
  fi
done

if (( ${#MISSING_EXPECTED[@]} > 0 )); then
  printf 'Warning: expected optional keys are not present: %s\n' "${MISSING_EXPECTED[*]}" >&2
fi

if grep -Eq "^BWS_ACCESS_TOKEN=" "$TMP_FILE"; then
  echo "Refusing to write BWS_ACCESS_TOKEN to $ENV_FILE." >&2
  exit 1
fi

chmod 600 "$TMP_FILE"
mv "$TMP_FILE" "$ENV_FILE"
trap - EXIT

echo "Wrote $ENV_FILE from Bitwarden project $BWS_PROJECT_ID."
