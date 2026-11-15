# Deploying the pilot from GitHub

| Piece | Where it runs | How it deploys |
|---|---|---|
| Website | Cloudflare Pages project `vv-pilot` (account Vitevue) | Automatically: the `deploy-website` job in `.github/workflows/frontend.yml` runs after the frontend checks pass. A push to `VV` deploys production; a pull request from this repo deploys a preview (`pr-<number>.vv-pilot.pages.dev`). |
| Backend | Hetzner 16 GB server, systemd `vv-api` + `vv-whatsapp-worker` | By hand from GitHub: Actions → **Deploy backend** → Run workflow on `VV`. |
| Old site | Pages project `vitevue-platform`, backend on ph-box | Not touched. `docker-publish.yml` no longer runs on pushes to `production`. |

## What the backend deploy does

`deploy-backend.yml` connects to the server over SSH through the server's Cloudflare
tunnel (`deploy-ssh.vitevue.com`, protected by a Cloudflare Access service token), then:

1. pushes the commit into the server's bare repo `~/vv.git` (branch `deploy`, fast-forward only);
2. runs `~/deploy/vv-deploy.sh <sha>` on the server, which
   - refuses to run if another deploy is running, the checkout has local edits, or the commit
     does not contain what is running now;
   - backs up Postgres to `~/backups/vitevue-pre-deploy-<sha>-<time>.dump` and `.env.dev`;
   - fast-forwards `~/vv`, restarts `vv-api` (its `ExecStartPre` runs `alembic upgrade head`)
     and `vv-whatsapp-worker`, and waits up to 5 minutes for `/api/v1/health`;
   - if the health check fails and the release changed no migrations, puts the previous
     commit back and restarts. If migrations changed, it stops and prints the backup path.

The deploy key can only do those two things: `authorized_keys` forces every login with it
through `vv-deploy-gate.sh`.

## One-time setup

### 1. Server (done by Maan over Tailscale)

```bash
install -d -m 700 ~/deploy
install -m 755 deploy/hetzner/vv-deploy-gate.sh deploy/hetzner/vv-deploy.sh ~/deploy/
# then add the deploy public key to ~/.ssh/authorized_keys as:
# restrict,command="/home/maan/deploy/vv-deploy-gate.sh" ssh-ed25519 AAAA... github-actions-deploy
```

### 2. Cloudflare (Maan, Zero Trust dashboard)

1. Networks → Tunnels → `vv-pilot-local` → Public hostnames → add
   `deploy-ssh.vitevue.com` → service `ssh://localhost:22`.
2. Access → Service auth → create service token `github-deploy-backend`.
3. Access → Applications → add a self-hosted app for `deploy-ssh.vitevue.com` with one
   policy: action **Service Auth**, include that service token.
4. My Profile → API Tokens → create a token with **Account → Cloudflare Pages → Edit** for
   the Vitevue account only (for the website job).

### 3. GitHub repository secrets (repo owner: Kian)

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `CLOUDFLARE_API_TOKEN` | the Pages token from step 2.4 |
| `CF_ACCESS_CLIENT_ID` | service token Client ID from step 2.2 |
| `CF_ACCESS_CLIENT_SECRET` | service token Client Secret from step 2.2 |
| `VV_DEPLOY_SSH_KEY` | the deploy private key (whole file, including the BEGIN/END lines) |

Without `CLOUDFLARE_API_TOKEN` the website job only prints a warning. Without the other three,
**Deploy backend** fails at its first step and changes nothing.

Send secret values to Kian through a password manager share, never in chat or email.

### 4. Backend CORS for preview deploys

In the server's `~/vv/.env.dev`, so that preview sites can call the API:

```
ALLOWED_ORIGIN_REGEX=^https://[a-z0-9-]+\.vv-pilot\.pages\.dev$
```

## Rolling back

- **Website:** Cloudflare dashboard → Pages → `vv-pilot` → Deployments → pick an older
  production deployment → *Rollback to this deployment*. Or
  `CLOUDFLARE_ACCOUNT_ID=083b3f7d7b4ec9b9fa911ebed2fbf024 bunx wrangler pages deployment list --project-name vv-pilot`.
- **Backend without migrations:** deploys only move forward, so roll back over SSH:
  `cd ~/vv && git reset --hard <previous-sha> && sudo systemctl restart vv-api vv-whatsapp-worker`.
- **Backend with migrations:** restore the `~/backups/vitevue-pre-deploy-*.dump` printed by the
  failed run (`pg_restore --clean`), then reset the code as above.

## Nightly database backups

`vv-backup.sh` runs from systemd timer `vv-backup.timer` every night at about 01:30 UTC.

1. It dumps Postgres to `~/backups/nightly` and checks that the dump can be read back (`pg_restore --list`).
2. It keeps 14 days of local copies.
3. If `~/.config/vv-backup/r2.env` exists, it also copies each dump to the private R2 bucket
   `vv-db-backups` (Western Europe). The bucket deletes objects after 30 days.

Install:

```bash
install -m 755 deploy/hetzner/vv-backup.sh ~/deploy/
sudo apt-get install -y rclone
```

The systemd units are `/etc/systemd/system/vv-backup.{service,timer}`, with `User=maan`,
`OnCalendar=*-*-* 01:30:00 UTC` and `Persistent=true`.

To turn on the off-server copy, create an R2 API token with *Object Read & Write* on
`vv-db-backups` only, then:

```bash
ssh -t maan@100.117.68.71 'mkdir -p ~/.config/vv-backup && umask 077 && read -p "Access Key ID: " a && read -s -p "Secret Access Key: " s && printf "R2_ACCESS_KEY_ID=%s\nR2_SECRET_ACCESS_KEY=%s\n" "$a" "$s" > ~/.config/vv-backup/r2.env && echo && ~/deploy/vv-backup.sh'
```

Restore: `docker exec -i vv-postgres-1 pg_restore -U vitevue -d vitevue --clean --if-exists < <dump>`.
Take a fresh dump first.

### Proving a backup restores

A dump that was never restored is a guess. `deploy/hetzner/vv-restore-test.sh [dump]` (install
with the other scripts: `install -m 755 deploy/hetzner/vv-restore-test.sh ~/deploy/`) restores
the newest nightly dump (or the one you name) into a throwaway `postgres:16-alpine` container
with no network and a 3 GB memory cap, never the live one, then compares the exact row count of
every table in the `public` and `auth` schemas with live and removes the container. It exits
non-zero on a failed restore, a missing table or a restored table larger than live; tables that
grew since the dump are listed, not failures. It takes about 3 minutes and 1 GB of RAM
and runs fine beside the live stack. Run it after any change to the backup script and at least
monthly. First run 2026-11-15: the 01:39 nightly dump (345 MB) restored without errors in 177 s,
66 of 68 tables identical to live and the other two (`crm_inbound_matches`,
`crm_mutation_audit`) only newer in live; a fresh dump restored identical on all 68.

To restore for real, take a fresh dump of whatever is live first, then
`docker exec -i vv-postgres-1 pg_restore -U vitevue -d vitevue --clean --if-exists < <dump>`
(stop `vv-api` and `vv-whatsapp-worker` first so nothing writes during the restore).

### What is not backed up yet

Only Postgres has a nightly backup. Nothing off the box either until `~/.config/vv-backup/r2.env`
exists (needs R2 credentials from the account owner).

| Store | Size on 2026-11-15 | Backup today | What it needs |
| --- | --- | --- | --- |
| Postgres | 6.5 GB live, 345 MB dump | nightly local dump, 14 days | R2 credentials for the off-box copy |
| ClickHouse | 15.2 GiB in tables (13.7 GB on disk after the 2026-11-15 cleanup) | none; `~/backup_ch.sh` writes market/DXBI tables only (2.3 GB zstd) before manual backfills | Most of it is rebuildable (DLD bronze reloads from open data, DXBI from the scraper evidence in `/srv/dxbi-evidence`). A nightly `BACKUP DATABASE vitevue TO S3(...)` needs a disk or S3 endpoint declared in the server config, about 14 GB first run, compressed by zstd to roughly 8-10 GB, then incremental with `base_backup`. Cheapest useful copy: the market, DXBI and `market_release_ledger` tables (about 2.5 GB zstd) |
| MinIO | 2.5 GB (`holocron-fresh`, `vitevue-dev`, `vitevue-etl`) | none | `rclone sync` of the three buckets to R2 (needs the same credentials); small enough to run nightly |
| Redis | 0.4 GB (AOF) | none | cache only; nothing to back up |

## Postgres tuning

`vv-postgres-1` runs with explicit settings, kept in `~/stack/compose.yml` (service `postgres`,
key `command`, plus `shm_size: 512mb`) so `docker compose up -d` keeps them. Before 2026-11-15 it
ran on image defaults (shared_buffers 128 MB on a 6.5 GB database). Values for the 16 GB box,
which also holds ClickHouse (capped at 9 GB), the API and the worker:

| Setting | Value | Why |
| --- | --- | --- |
| `shared_buffers` | 2GB | about a third of the database; leaves the rest of RAM to ClickHouse and the page cache |
| `effective_cache_size` | 6GB | planner hint for the OS cache it can count on |
| `work_mem` | 16MB | fewer sort and hash spills; about 10 live connections, `max_connections` stays 100 |
| `maintenance_work_mem` | 256MB | VACUUM and index builds |
| `random_page_cost` | 1.1 | SSD |
| `effective_io_concurrency` | 200 | SSD |
| `wal_buffers` / `max_wal_size` / `min_wal_size` | 16MB / 4GB / 1GB | fewer forced checkpoints during imports |
| `track_io_timing` | on | I/O time in `EXPLAIN` and `pg_stat_statements` |
| `log_min_duration_statement` | 1000 | log statements slower than 1 s |
| `shared_preload_libraries` | `pg_stat_statements` | `pg_stat_statements.max=5000`, `track=top`; run `CREATE EXTENSION pg_stat_statements` once per database |

Changing any of these needs a container recreate (about 6 s, the API reconnects by itself):

```bash
cd ~/stack && cp compose.yml compose.yml.bak-$(date -u +%Y%m%d)
# edit the `command:` list, then take a fresh dump (deploy/hetzner/vv-backup.sh) and:
docker compose up -d --no-deps postgres
docker exec vv-postgres-1 psql -U vitevue -d vitevue -c 'show shared_buffers'
```

Slow queries: `select calls, round(mean_exec_time) ms, left(query, 100) from pg_stat_statements
order by total_exec_time desc limit 10;`. Autovacuum already keeps the large `crm_*` tables
at zero dead tuples; `VACUUM (ANALYZE) <table>` is only needed after a bulk delete.

## Daily DXBI warehouse sync

Scraped DXBI data reaches the live ClickHouse by itself. The scrapers stay on the 4 GB box
(`dxbi-sales-daily.timer` 22:30 UTC, `dxbi-rentals-daily.timer` 00:30 UTC); they write
`/root/data/dxbi-daily/{sales,rentals}/run=YYYY-MM-DD/` and touch `_SUCCESS` only when every shard
finished.

`vv-dxbi-sync.timer` on the 16 GB server (04:00 and 12:00 UTC) runs `vv-dxbi-sync.sh`:

1. **Pull.** rsync over Tailscale with its own key (`~/.ssh/dxbi_pull_ed25519`) into
   `/srv/dxbi-evidence/dxbi-daily`. On the 4 GB box that key is forced through
   `/usr/local/sbin/dxbi-pull-gate`, which allows only a read of `/root/data/dxbi-daily`.
2. **Load.** `sync_dxbi_to_warehouse.py` loads each run that has `_SUCCESS` and no marker in
   `~/.local/state/vv-dxbi-sync/loaded`, oldest first, with `load_dxbi_sales_units.py` or
   `load_dxbi_rental_events.py --target active`, each with `--replace-window` set to the dates the
   run's own checkpoint covers. A run without `_SUCCESS` is never loaded, so the failing rentals
   scrape costs nothing until it succeeds. A run is marked only after its load succeeds.
   The newest complete data for a day wins whatever order runs finish in: a run that gets its
   `_SUCCESS` after a newer run was loaded replaces only the days no newer loaded run covers (it
   loads just those days' shards, each stretch of consecutive days with its own `--replace-window`)
   and is only marked when none are left. No marker needs deleting by hand for this.
3. **Release.** After anything was loaded: `materialize_market_sale_events`,
   `materialize_market_rental_events`, `build_profiles`, then the Redis `transactions:` and
   `analytics:` keys are cleared. `release-pending` in the state directory keeps a failed build owed.
4. **Owners lease links.** Every run (unless a load or the release failed) then runs
   `backend/scripts/crm/refresh_rental_imports.py --state-dir ~/.local/state/vv-dxbi-sync/owners`
   from `~/vv/backend`. It gives each imported claim the current lease of its unit (lease id, lease
   end, rent; the rule in `ownership.refresh_property_contact_rentals`: a source unit number or a
   unique sale match, lease end between today - 365 and today + 90). Owners, contacts, statuses and
   imports are not changed. Then every organization whose stored owner assessment is out of date
   gets a new generation (`owner_store.publish_if_stale`), so the Owners page serves it without a
   visitor's request building it. It runs on every sync because the lease window moves daily;
   `owners/import-rental-matches.json` makes an unchanged day cheap. Measured on the pilot
   (311,665 claims): 10 min in all (link refresh ~2 min, then the new generation), peak RSS 1.4 GB.

The unit fails (and the journal shows why) when a load, the release or the Owners refresh fails,
or when there is no finished sales run or no finished rentals run in 36 hours. The failed unit
shows in `systemctl --failed` and the journal (`No finished rentals run in the last 36 hours`);
there is no other alert channel.

Install (16 GB server, as maan):

```bash
install -m 755 deploy/hetzner/vv-dxbi-sync.sh ~/deploy/
install -m 644 holocron/holocron/platform/sync_dxbi_to_warehouse.py ~/deploy/
ssh-keygen -t ed25519 -N '' -C vv-dxbi-pull -f ~/.ssh/dxbi_pull_ed25519
sudo install -m 644 deploy/hetzner/vv-dxbi-sync.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now vv-dxbi-sync.timer
```

Install (4 GB box): `sudo install -m 755 deploy/hetzner/dxbi-pull-gate.sh /usr/local/sbin/dxbi-pull-gate`, then add to
`~maan/.ssh/authorized_keys`:
`restrict,command="/usr/local/sbin/dxbi-pull-gate" <contents of dxbi_pull_ed25519.pub>`.

### Release copies and memory in ClickHouse

Each market release (`market_sale_events`, `market_rental_events`) keeps the table it replaced as
`<table>__previous` (the rollback target) and an immutable pinnable copy
`<table>__r<release_id>`. Every release builds its own parts, so a retained copy costs a full
table (rentals 1.4 GiB). Cleanup runs after every publication and keeps the live release, the
release `__previous` holds and any copy superseded less than 2 hours ago
(`RELEASE_RETENTION`, `docs/data-pipelines/MARKET_RELEASE_CONTRACT.md`). Before 2026-11-15 the
window was 24 hours and four re-runs on 2026-11-14 left six copies (5.2 GiB of real disk), which
were dropped by hand (list in `~/backups/ch-cleanup-2026-11-15.txt`). To check:
`python -m holocron.market.release recover` prints what it drops.

Every INSERT of a release build runs with `max_memory_usage = 6.5e9`, one insert stream and
500 MB external sort/group-by thresholds; the events inserts also cap `max_threads`. Measured on
this box: sale events 7.0 to 3.9 GiB at peak, rental events 4.9 to 4.3 GiB. Check a run with
`select event_time, round(memory_usage/1073741824,2) gib, left(query,60) from system.query_log
where type='QueryFinish' and query like '%INSERT INTO%market_%events__staging%' order by
event_time desc limit 10`.

Back up the DXBI and market tables before a manual backfill with `~/backup_ch.sh` (writes
`~/backups/ch-pre-backfill-<time>`). To reload a run, delete its marker
(`rm ~/.local/state/vv-dxbi-sync/loaded/sales-run=YYYY-MM-DD`) and start the service. A reloaded
run still skips days that a newer loaded run covers; delete those runs' markers too to reload them.
