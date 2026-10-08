#!/usr/bin/env bash
# Nightly DXBI location sweep: DXBI's own search for every area and community over the last
# days, so the Transactions Location filter groups new sales and leases as DXBInteract's area
# pages do. Holocron's dxbi_evidence_load (10:00 Dubai) loads each finished run; a run replaces
# only the memberships inside its window (scripts/load_dxbi_location_members.py).
set -euo pipefail

report="${1:-}"
case "$report" in
  sales) account="a" ;;
  rentals) account="b" ;;
  *)
    echo "usage: $0 sales|rentals" >&2
    exit 64
    ;;
esac

repo_dir="${DXBI_REPO_DIR:-/root/repos/vitevue-platform}"
data_dir="${DXBI_DAILY_DATA_DIR:-/root/data/dxbi-daily}"
config_dir="${DXBI_CONFIG_DIR:-/root/.config/vitevue/dxbi}"
browser="${DXBI_BROWSER:-/root/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome}"
window_days="${DXBI_SWEEP_WINDOW_DAYS:-14}"
timeout_duration="${DXBI_SWEEP_TIMEOUT:-3h}"
# Dubai's calendar date, although the server clock is UTC: at 03:30 Dubai it is still the
# previous day in UTC, and the window must end on Dubai's today.
run_date="$(TZ=Asia/Dubai date +%F)"
start_date="$(TZ=Asia/Dubai date -d "${run_date} - ${window_days} days" +%F)"
template_date="$(TZ=Asia/Dubai date -d "${run_date} - 1 day" +%F)"
output_dir="${data_dir}/${report}-sweep/run=${run_date}-nightly"
# The report's scrape lock: one DXBI session per account, and the sweep follows the scrape.
lock_file="/run/lock/vitevue-dxbi-${report}.lock"

mkdir -p "$output_dir"
record_failure() {
  exit_code=$?
  trap - EXIT
  if (( exit_code != 0 )) && [[ ! -f "${output_dir}/_SUCCESS" ]]; then
    failure_tmp="${output_dir}/_FAILURE.tmp.$$"
    printf '{"status":"failed","exit_code":%d,"failed_at":"%s"}\n' \
      "$exit_code" "$(date -u +%FT%TZ)" > "$failure_tmp"
    mv "$failure_tmp" "${output_dir}/_FAILURE"
  fi
  exit "$exit_code"
}
trap record_failure EXIT
exec 9>"$lock_file"
echo "Waiting for the shared ${report} scrape lock."
flock 9

/usr/bin/timeout --signal=TERM --kill-after=30s "$timeout_duration" \
  "${repo_dir}/holocron/.venv/bin/python" \
  "${repo_dir}/holocron/scripts/dxbi_location_sweep.py" \
  --credentials "${config_dir}/account-${account}.json" \
  --storage-state "${config_dir}/account-${account}-state.json" \
  --browser "$browser" \
  --output-dir "$output_dir" \
  --start-date "$start_date" \
  --end-date "$run_date" \
  --template-date "$template_date" \
  --delay-min 2 \
  --delay-max 4 \
  --report "$report"

if [[ ! -f "${output_dir}/_SUCCESS" ]]; then
  echo "${report} sweep exited without a terminal success marker" >&2
  exit 1
fi
