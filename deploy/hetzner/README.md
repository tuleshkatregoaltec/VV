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
