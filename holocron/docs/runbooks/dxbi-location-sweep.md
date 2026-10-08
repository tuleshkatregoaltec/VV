# DXB Interact location sweep

The Transactions Location filter groups sales and leases the way DXBI's own area pages do
(decision 2026-10-07). DXBI's pages can count a sale under a different place than the area printed
on its row. In August 2026, JVC's page counted buildings printed only "Al Barsha South 4", and
Dubai Marina's page counted 154 sales while 181 rows printed "Dubai Marina". DXBI's report rows carry
no location id, so the grouping is learned by running DXBI's own search for each location.

## What runs

1. `scripts/dxbi_location_sweep.py` signs in and reads DXBI's location list
   (`https://dxbinteract.com/property/website/DLDLOV?RETURN_COLUMN=LOCATION_URL`: about 7,300
   nodes, from areas down to buildings). It then searches sales for every area (`A`), sub-area
   (`U`) and master community (`M`), about 360 locations, over the window.
   - DXBI returns at most 300 rows per search and offers no next page. A full search is split by
     dates, then by price and size within a day, until every part returns fewer.
   - Output: `location=<id>.jsonl.gz` per location, plus `locations.json`, `summary.json` and
     `_SUCCESS`. Finished locations are skipped on a re-run.
2. `scripts/load_dxbi_location_members.py <run dir>` replaces `dxbi_locations` (each location with
   the areas above it) and `dxbi_location_members` (the sales each location's search returned).
   Each table is swapped in one step.

A record's locations in the app are, in order:

1. the locations whose search returned it;
2. otherwise, the locations that returned other sales in its building (leases use this);
3. otherwise, the location named like its printed area, plus the areas above it.

## Running it

Use the same credentials file, storage state and browser as the rental backfill
(`dxbi-rental-v2.md`), and one DXBI session at a time: do not run it beside a backfill on the
same account.

```bash
python scripts/dxbi_location_sweep.py \
  --credentials /secure/account-b.json \
  --storage-state /secure/account-b-state.json \
  --browser /path/to/chrome \
  --output-dir /data/dxbi-location-sweep/run=2026-10-07 \
  --start-date 2025-10-01 --end-date 2026-10-07

python scripts/load_dxbi_location_members.py /data/dxbi-location-sweep/run=2026-10-07
```

A 12-month window covers the buildings of 96% of the following year's sales (6 months: 90%).
Re-run it monthly so new buildings are placed. The 12-month sales sweep of 2026-10-08 made 3,218
searches in 6 hours (6.7 s each at the scraper's 3-6 second pace).

**Leases.** DXBI's rental area pages group leases with their own search too. Run the same sweep
with `--report rentals` into its own run directory, then load it the same way: it fills
`dxbi_location_lease_members` by the leases' `contract_key`, and the Rentals page uses it before
the building and printed-area fallbacks. Leases are about 2.5 times the sales searches, roughly 15
hours for 12 months.

## Checking it

The sweep reproduces DXBI's summary cards: for August 2026, JVC (location 36510) returned 761
sales and Dubai Marina (31987) 154, the same as the cards on their area pages.
`backend/scripts/clickhouse/verify_dxbi_transactions.py` re-implements the rule and checks the API
against it.

## Nightly in production (Dubai time)

Every DXBI job keys on Dubai's calendar (`TZ=Asia/Dubai`), although the servers run in UTC. Dubai
is UTC+4 all year (no daylight saving).

| Dubai time (GST) | UTC | Job | Account | Typical length |
|---|---|---|---|---|
| 02:30 | 22:30 (day before) | `dxbi-sales-daily`: sales scrape of the last 7 days | a | ~15 min |
| 03:30 | 23:30 (day before) | `dxbi-sales-sweep`: sales sweep of the last 14 days | a | ~45-60 min |
| 04:30 | 00:30 | `dxbi-rentals-daily`: lease scrape of the last 14 days | b | ~1-3 h |
| 06:30 | 02:30 | `dxbi-rentals-sweep`: lease sweep of the last 14 days | b | ~1 h |
| Sun 06:00 | Sun 02:00 | `dxbi-rentals-weekly`: leases 15-180 days back | b | up to 12 h |
| 10:00 | 06:00 | Dagster `dxbi_evidence_load`: archives and loads every finished run | - | minutes |
| 10:30 | 06:30 | Dagster `market_events_refresh`: rebuilds the Analytics releases | - | ~5 min |

- **One session per account.** A sweep takes its report's scrape lock
  (`/run/lock/vitevue-dxbi-<report>.lock`), so it waits while that account's scrape runs, and a
  late scrape delays its sweep rather than overlapping it. It waits at most 55 minutes
  (`DXBI_SWEEP_LOCK_WAIT_SECONDS`): when the Sunday weekly or the monthly lease scrape holds the
  account (up to 12 and 24 hours), the sweep skips that night without a failure marker, and the
  next night's 14-day window covers the missed days.
- **Loading.** The evidence load takes each finished run (`_SUCCESS`) once (ledger
  `dxbi_evidence_load_ledger`) and archives its raw files to object storage first.
  - A scrape run that completed every day of an unbroken window loads alone with
    `--replace-window` (oldest first, so two runs never replace the days between them).
  - A sweep run replaces only the memberships dated in its window, so nights add to the first
    12-month run and a re-run is harmless.
- **Failures.** A run that fails or times out writes `_FAILURE` and is never loaded. The
  previous night's data keeps serving, and the next night's 14-day window covers the missed
  days. DXBI's Cloudflare answers 520/522 at times; the scraper retries each request 3 times.

**Install** (as for the existing DXBI units):

```bash
install -m 0755 holocron/deploy/systemd/dxbi-location-sweep.sh /usr/local/sbin/dxbi-location-sweep
install -m 0644 holocron/deploy/systemd/dxbi-{sales,rentals}-sweep.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dxbi-sales-sweep.timer dxbi-rentals-sweep.timer
systemctl list-timers 'dxbi-*'   # next runs, shown in UTC
```

Before the first night, run the 12-month sweep once per report by hand (above): about 6 hours
for sales and about 15 for leases. `DXBI_SWEEP_WINDOW_DAYS` (default 14) and
`DXBI_SWEEP_TIMEOUT` (default 3h) tune the nightly run.
