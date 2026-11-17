#!/usr/bin/env bash
# Daily DXBI warehouse sync on the 16 GB server (systemd timer vv-dxbi-sync.timer).
#
# 1. Pull the scraper box's runs (/root/data/dxbi-daily) into /srv/dxbi-evidence/dxbi-daily.
# 2. Load every finished run (_SUCCESS) not yet loaded, rebuild the market releases and
#    profiles, clear the API caches (sync_dxbi_to_warehouse.py does step 2).
# ClickHouse settings come from the unit's EnvironmentFile (~/vv/.env.dev).
set -euo pipefail

repo="${VV_REPO_DIR:-$HOME/vv}"
remote="${DXBI_REMOTE:-maan@100.67.219.109}"
evidence="${DXBI_EVIDENCE_DIR:-/srv/dxbi-evidence/dxbi-daily}"
state="${DXBI_SYNC_STATE_DIR:-$HOME/.local/state/vv-dxbi-sync}"
key="${DXBI_PULL_KEY:-$HOME/.ssh/dxbi_pull_ed25519}"
attempts="${DXBI_PULL_ATTEMPTS:-5}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

mkdir -p "$evidence"
for ((i = 1; i <= attempts; i++)); do
	if rsync -a --partial --timeout=120 --no-owner --no-group --chmod=D755,F644 \
		--rsync-path="sudo rsync" \
		-e "ssh -i $key -o BatchMode=yes -o IdentitiesOnly=yes" \
		"$remote:/root/data/dxbi-daily/" "$evidence/"; then
		log "pulled runs from $remote"
		break
	fi
	if ((i == attempts)); then
		log "pull failed after $attempts attempts"
		exit 1
	fi
	log "pull attempt $i failed; retrying in 30s"
	sleep 30
done

export PYTHONPATH="$repo/holocron"
exec "$repo/backend/.venv/bin/python" "$HOME/deploy/sync_dxbi_to_warehouse.py" \
	--repo-dir "$repo" --evidence-dir "$evidence" --state-dir "$state"
