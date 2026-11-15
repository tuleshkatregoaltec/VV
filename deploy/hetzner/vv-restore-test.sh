#!/usr/bin/env bash
# Prove a Postgres backup restores: load a dump into a throwaway container (never the live one)
# and compare exact row counts of every table in the public and auth schemas with live.
#
#   vv-restore-test.sh [dump]       default: the newest dump in ~/backups/nightly
#
# Exit 0 when every table has rows and the only differences are tables that grew since the
# dump was taken (restored <= live); non-zero on a failed restore, a missing table or a
# restored table larger than live.
set -euo pipefail

dump="${1:-$(ls -t "$HOME"/backups/nightly/vitevue-*.dump | head -1)}"
name="vv-restore-test-$$"
live="vv-postgres-1"
log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

counts='select schemaname||$$.$$||relname, (xpath($$/row/c/text()$$, query_to_xml(format($$select count(*) as c from %I.%I$$, schemaname, relname), false, true, $$$$)))[1]::text::bigint from pg_stat_user_tables where schemaname in ($$public$$,$$auth$$) order by 1'

log "restoring $dump ($(du -h "$dump" | cut -f1)) into throwaway container $name"
# No published port and no network: the throwaway database is unreachable from outside.
docker run -d --name "$name" --network none --memory 3g \
	-e POSTGRES_USER=vitevue -e POSTGRES_PASSWORD=restoretest -e POSTGRES_DB=restore \
	postgres:16-alpine >/dev/null
for _ in $(seq 1 30); do
	docker exec "$name" pg_isready -U vitevue -d restore >/dev/null 2>&1 && break
	sleep 2
done
start=$(date +%s)
docker exec -i "$name" pg_restore -U vitevue -d restore --no-owner --no-privileges --exit-on-error <"$dump"
log "restored in $(($(date +%s) - start))s"

restored=$(mktemp) livecounts=$(mktemp)
docker exec "$name" psql -U vitevue -d restore -XAt -F'|' -c "$counts" >"$restored"
docker exec "$live" psql -U vitevue -d vitevue -XAt -F'|' -c "$counts" >"$livecounts"

join -t'|' -a1 -a2 -e MISSING -o 0,1.2,2.2 "$restored" "$livecounts" |
	awk -F'|' '
	  { total++ }
	  $2 == $3 { same++; next }
	  $2 == "MISSING" || $3 == "MISSING" || $2 > $3 { bad++; printf "FAIL %-45s restored=%s live=%s\n", $1, $2, $3; next }
	  { printf "grew since dump: %-36s restored=%s live=%s (+%d)\n", $1, $2, $3, $3 - $2 }
	  END { printf "%d tables compared, %d identical, %d failing\n", total, same, bad; exit bad > 0 }'
log "restore test passed"
rm -f "$restored" "$livecounts"
