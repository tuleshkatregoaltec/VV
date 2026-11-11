#!/usr/bin/env bash
# Deploy one commit of Kian-Sham/VV to the pilot backend server.
#
# Installed as ~/deploy/vv-deploy.sh. Called by vv-deploy-gate.sh (GitHub Actions)
# or by hand:  ~/deploy/vv-deploy.sh <full-sha>
#
# Steps: lock -> check the commit is on the bare repo's deploy branch -> refuse a dirty
# checkout -> pg_dump backup -> fast-forward ~/vv -> restart vv-api (its ExecStartPre runs
# alembic) and vv-whatsapp-worker -> health check. If the health check fails and the
# release changed no migrations, the code is put back to the previous commit and restarted.
set -euo pipefail

sha="${1:?usage: vv-deploy.sh <full-commit-sha>}"
repo="$HOME/vv"
bare="$HOME/vv.git"
backups="$HOME/backups"
health_url="http://127.0.0.1:8000/api/v1/health"
services=(vv-api vv-whatsapp-worker)

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

exec 9>"$HOME/deploy/.lock"
if ! flock -n 9; then
	log "another deploy is running; stopping"
	exit 1
fi

if ! git -C "$bare" merge-base --is-ancestor "$sha" refs/heads/deploy 2>/dev/null; then
	log "commit $sha is not on the deploy branch of $bare (push it first)"
	exit 1
fi

cd "$repo"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
	log "$repo has uncommitted changes to tracked files; refusing to deploy"
	git status --short --untracked-files=no
	exit 1
fi

prev="$(git rev-parse HEAD)"
if [[ "$prev" == "$sha" ]]; then
	log "server already runs $sha; restarting only"
fi

git fetch --quiet origin
if ! git merge-base --is-ancestor "$prev" "$sha"; then
	log "$sha does not contain the running commit $prev; refusing a non-fast-forward deploy"
	exit 1
fi

stamp="$(date -u +%Y%m%d-%H%M%S)"
dump="$backups/vitevue-pre-deploy-${sha:0:7}-$stamp.dump"
mkdir -p "$backups"
log "backing up Postgres to $dump"
docker exec vv-postgres-1 pg_dump -U vitevue -Fc vitevue >"$dump"
cp "$repo/.env.dev" "$backups/env.dev.pre-deploy-${sha:0:7}-$stamp"
log "backup size $(du -h "$dump" | cut -f1)"

migrations_changed=0
if ! git diff --quiet "$prev" "$sha" -- backend/migrations; then
	migrations_changed=1
	log "this release changes database migrations"
fi

log "moving $prev -> $sha"
git merge --ff-only --quiet "$sha"

restart() {
	for service in "${services[@]}"; do
		log "restarting $service"
		sudo systemctl restart "$service"
	done
}

healthy() {
	for _ in $(seq 1 60); do
		if curl -fsS -m 5 "$health_url" >/dev/null 2>&1; then
			for service in "${services[@]}"; do
				systemctl is-active --quiet "$service" || return 1
			done
			return 0
		fi
		sleep 5
	done
	return 1
}

restart || true
if healthy; then
	log "deployed $sha; health check passed"
	exit 0
fi

log "health check FAILED for $sha"
journalctl -u vv-api -n 40 --no-pager || true
if [[ "$migrations_changed" == 1 ]]; then
	log "migrations changed, so no automatic rollback. Database backup: $dump"
	log "manual rollback: restore the dump, then: cd $repo && git reset --hard $prev && sudo systemctl restart ${services[*]}"
	exit 1
fi

log "rolling code back to $prev"
git reset --hard --quiet "$prev"
restart || true
if healthy; then
	log "rolled back to $prev; it is healthy again"
else
	log "rollback to $prev is ALSO unhealthy; check journalctl -u vv-api"
fi
exit 1
