#!/usr/bin/env bash
# Nightly Postgres backup for the pilot server (systemd timer vv-backup.timer).
#
# 1. pg_dump (custom format) into ~/backups/nightly, checked with pg_restore --list.
# 2. Local copies older than 14 days are removed.
# 3. If ~/.config/vv-backup/r2.env exists (R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY),
#    the dump is also copied to Cloudflare R2 bucket vv-db-backups (off-server copy).
set -euo pipefail

dir="$HOME/backups/nightly"
r2_env="$HOME/.config/vv-backup/r2.env"
r2_endpoint="https://083b3f7d7b4ec9b9fa911ebed2fbf024.r2.cloudflarestorage.com"
r2_bucket="vv-db-backups"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

mkdir -p "$dir"
stamp="$(date -u +%Y%m%d-%H%M%S)"
out="$dir/vitevue-$stamp.dump"

log "dumping Postgres to $out"
docker exec vv-postgres-1 pg_dump -U vitevue -Fc vitevue >"$out.part"
docker exec -i vv-postgres-1 pg_restore --list <"$out.part" >/dev/null
mv "$out.part" "$out"
log "dump ok ($(du -h "$out" | cut -f1))"

find "$dir" -name 'vitevue-*.dump' -mtime +14 -print -delete

if [[ -f "$r2_env" ]]; then
	set -a
	# shellcheck disable=SC1090
	. "$r2_env"
	set +a
	log "copying to R2 bucket $r2_bucket"
	RCLONE_CONFIG_R2_TYPE=s3 \
		RCLONE_CONFIG_R2_PROVIDER=Cloudflare \
		RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
		RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
		RCLONE_CONFIG_R2_ENDPOINT="$r2_endpoint" \
		rclone copyto "$out" "r2:$r2_bucket/postgres/$(basename "$out")" --s3-no-check-bucket
	log "R2 copy ok"
else
	log "no $r2_env yet: local copy only (no off-server backup)"
fi
