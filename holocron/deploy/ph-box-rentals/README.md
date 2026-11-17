# Nightly DXBI rentals on the 4GB scraper box (ph-box)

What is deployed on `debian-4gb-nbg1-1` (`ssh maan@100.67.219.109`) for the nightly lease scrape,
as of 2026-11-14. Sales are not part of this: `dxbi-sales-daily` still runs
`/usr/local/sbin/dxbi-report-daily sales` and the untracked
`/root/repos/vitevue-platform/holocron/scripts/dxbi_rental_backfill.py`, both unchanged.

| Box path | Source in this folder |
| --- | --- |
| `/usr/local/lib/vitevue-dxbi-rentals/dxbi_rental_backfill_legacy.py` | `dxbi_rental_backfill_legacy.py` |
| `/usr/local/sbin/dxbi-rentals-daily` | `dxbi-rentals-daily.sh` |
| `/etc/systemd/system/dxbi-rentals-daily.service` | `dxbi-rentals-daily.service` |
| `/etc/systemd/system/dxbi-rentals-daily.timer` | `dxbi-rentals-daily.timer` |

The scraper is the box's own older collector (the untracked file above, last changed 2026-08-26),
with only the outage handling below added. It runs in the box's existing
`/root/repos/vitevue-platform/holocron/.venv` and writes the same output as before:
`/root/data/dxbi-daily/rentals/run=YYYY-MM-DD/` (Dubai date) with `checkpoint.json`,
`shards/<lease date>/*.jsonl.gz` and `_SUCCESS` when every slice of the 8-day window
(D-7..D) is complete. `holocron/scripts/load_dxbi_rental_events.py` already loads this layout.
It is not the manifest-based collector in `holocron/scripts/dxbi_rental_backfill.py`: that one
needs a rental profile manifest, which the box does not have, and writes a different layout.

Backups of the files replaced on 2026-11-14 are on the box in
`/root/backups/dxbi-rentals-fix-20261114/`.

## Why it failed every night from 2026-10-30

1. From 2026-10-30 DXBI answers each whole-Dubai lease request in about 17-18 s; until 10-29 it
   took about 3 s. Page size and filters make no difference, a sales request on the same
   account and session still takes about 1.5 s, and a single area answers in 0.4 s. The 00:30 UTC
   run therefore grew from about 13 minutes to about 45.
2. DXBI's origin goes down every night at about 01:00 UTC (05:00 Dubai) and Cloudflare answers 520.
   All 15 failed runs made their last good request between 00:59:42 and 01:00:01 UTC, whatever
   their start time (00:30-00:35). July-September backfills on this box show the same gap
   starting at 01:00 or 01:15 UTC, lasting 20 minutes to over 2 hours.
3. The scraper treated 520 as fatal and raised, so the run ended without `_SUCCESS`, and the next
   night failed the same way.

## The fix

- The timer starts at 23:00 UTC (03:00 Dubai), after the sales scrape, so the ~45-minute run ends
  about 2 hours before the outage.
- A Cloudflare 52x now means "DXBI is down": the scraper waits (60, 120, 240, then every 300 s, up
  to `--outage-wait-minutes`, default 90), logs in again, captures a fresh request template and
  retries the slice. If DXBI is still down after that, it records the slice and stops.
- Any other slice that still fails after its retries is recorded in `checkpoint.json` under
  `failed`. The run carries on with the other slices and exits 1 at the end, so the wrapper writes
  no `_SUCCESS`. A re-run of the same run folder retries the failed slices; the old failures are
  kept under `failed_history`.
- A login redirect on the last attempt is a failure now. Before, it was stored as an empty slice
  (a false zero).
- The wrapper's timeout is 3 h (it was 90 min).

## Operating it

- Re-run or resume one night: `sudo /usr/local/sbin/dxbi-rentals-daily 2026-11-08`. It resumes
  that night's `checkpoint.json` under the same lock as the timer.
- Log: `sudo journalctl -u dxbi-rentals-daily`. `OUTAGE`, `FAILED` and `ABORT` lines mark the
  cases above.
- Roll back: copy the files back from `/root/backups/dxbi-rentals-fix-20261114/`
  (`dxbi-rentals-daily.service` there runs `/usr/local/sbin/dxbi-report-daily rentals`), then run
  `systemctl daemon-reload`.
