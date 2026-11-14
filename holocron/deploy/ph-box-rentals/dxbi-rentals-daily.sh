#!/usr/bin/env bash
# Nightly DXBI rentals scrape on the 4GB scraper box (ph-box), installed as
# /usr/local/sbin/dxbi-rentals-daily. Sales keep using /usr/local/sbin/dxbi-report-daily.
#
# Usage: dxbi-rentals-daily [RUN_DATE]
#   RUN_DATE (YYYY-MM-DD, Dubai calendar) re-runs or resumes that night's run folder through
#   its own checkpoint; the default is today in Dubai.
set -euo pipefail

account="b"
repo_dir="${DXBI_REPO_DIR:-/root/repos/vitevue-platform}"
script="${DXBI_RENTALS_SCRIPT:-/usr/local/lib/vitevue-dxbi-rentals/dxbi_rental_backfill_legacy.py}"
data_dir="${DXBI_DAILY_DATA_DIR:-/root/data/dxbi-daily}"
config_dir="${DXBI_CONFIG_DIR:-/root/.config/vitevue/dxbi}"
browser="${DXBI_BROWSER:-/root/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome}"
lookback_days="${DXBI_LOOKBACK_DAYS:-7}"
# Since 2026-10-30 DXBI takes ~18 s per whole-Dubai rental request (~45 min a night), and the
# scraper may wait up to 90 minutes for DXBI's nightly origin outage to end.
timeout_duration="${DXBI_RENTALS_TIMEOUT:-3h}"

# Use Dubai's calendar date even though the server clock is UTC. Re-reading a
# short rolling window captures late registrations; ReplacingMergeTree keys make
# the downstream load idempotent.
run_date="${1:-$(TZ=Asia/Dubai date +%F)}"
if [[ ! "$run_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "usage: $0 [YYYY-MM-DD]" >&2
  exit 64
fi
start_date="$(date -d "${run_date} - ${lookback_days} days" +%F)"
template_date="$(date -d "${run_date} - 1 day" +%F)"
output_dir="${data_dir}/rentals/run=${run_date}"
lock_file="/run/lock/vitevue-dxbi-rentals.lock"

exec 9>"$lock_file"
flock -n 9 || {
  echo "A rentals scrape is already running; exiting without overlap."
  exit 0
}
mkdir -p "$output_dir"

/usr/bin/timeout --signal=TERM --kill-after=30s "$timeout_duration" \
  "${repo_dir}/holocron/.venv/bin/python" -u "$script" \
  --credentials "${config_dir}/account-${account}.json" \
  --storage-state "${config_dir}/account-${account}-state.json" \
  --browser "$browser" \
  --output-dir "$output_dir" \
  --start-date "$start_date" \
  --end-date "$run_date" \
  --direction desc \
  --template-date "$template_date" \
  --delay-min 2 \
  --delay-max 4 \
  --outage-wait-minutes "${DXBI_OUTAGE_WAIT_MINUTES:-90}" \
  --report rentals

touch "${output_dir}/_SUCCESS"
