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
or when there is no finished sales run in 36 hours. No finished rentals run in 36 hours is a
logged warning.

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

Back up the DXBI and market tables before a manual backfill with `~/backup_ch.sh` (writes
`~/backups/ch-pre-backfill-<time>`). To reload a run, delete its marker
(`rm ~/.local/state/vv-dxbi-sync/loaded/sales-run=YYYY-MM-DD`) and start the service.
