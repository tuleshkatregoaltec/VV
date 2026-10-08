# Production rollout: DXBI-only Transactions, location grouping, Analytics fixes (October 2026)

What production needs after PRs #29 to #36 merge, in order. Every step was run on the local
warehouse first (2026-10-08). Steps marked **approval** spend money or touch shared data, and run
only once the owner agrees.

## 1. Deploy and schema

- Deploy the backend, frontend and Holocron from `VV`.
- Holocron's schema step creates `dxbi_locations` and `dxbi_location_members`
  (`holocron/holocron/lib/sql/clickhouse_schema.sql`). Until a sweep is loaded they stay empty, and
  the Location filter falls back to the printed areas.

## 2. DLD rents loaded on a UK-time machine (approval)

One rents load stored every midnight as 23:00 the evening before during UK summer time
(`DLD_LEASE_DATE_CORRECTION.md`). Check every run:

```sql
SELECT run_id, count() AS rows, countIf(toHour(start_date) = 23) AS start_at_23h
FROM dld_od_rents_bronze
GROUP BY run_id
HAVING start_at_23h > 0
ORDER BY start_at_23h DESC;
```

For each run listed, correct it as `DLD_LEASE_DATE_CORRECTION.md` describes:
1. Copy the run under a temporary id with `x + timeZoneOffset(toTimeZone(x, 'Europe/London'))`
   on `registration_date`, `start_date` and `end_date`.
2. Check the copy's count, delete the original run, and restore the run id.
3. Confirm the table total is unchanged.

## 3. DXBI sales (approval for the delete)

The loader now keeps sales whose unit DXBI hides, takes the building name DXBI shows, reads
units with spaces whole, and deletes older copies of a re-loaded sale.

- **History:** re-load the archived raw sales files on ph-box with
  `holocron/scripts/load_dxbi_sales_units.py <raw dirs>`. The raw files are on ph-box / the Mac,
  not in object storage (audit L13). Expect `without_unit` in the hundreds of thousands (audit L1:
  114,466 sales from 2014 to 2026) and `superseded` in the tens of thousands.
- **Recent window:** scrape with `holocron/scripts/dxbi_rental_backfill.py --report sales` for the
  window, then load it with `--replace-window FIRST LAST`. DXBI's latest listing then replaces
  those dates outright: CSV-export rows, and sales DXBI moved to another day.

## 4. DXBI leases (approval for the replace)

Scrape the window with `dxbi_rental_backfill.py --report rentals`. Re-run the scrape for any day
that ends `failed`: DXBI's Cloudflare returns 520/522 at times, and a re-run retries only those
days. Once every day is complete, load the day directories with
`holocron/scripts/load_dxbi_rental_events.py --replace-window FIRST LAST`. DXBI's listing then
replaces what is stored for those lease start dates. A plain load merges, and keeps leases only
older runs held: locally, 3,943 August leases from a test run put some areas 10-20% above DXBI.

## 5. Location sweeps

Follow `holocron/docs/runbooks/dxbi-location-sweep.md`: sweep sales and leases (`--report
rentals`) over the last 12 months, then `load_dxbi_location_members.py <run dir>` for each.
Re-run monthly.

## 6. Market releases

Rebuild both releases from `holocron/` with the production settings:

```python
from holocron.platform.clickhouse import ClickHouseClient
from holocron.platform.settings import Settings
from holocron.market import release

client = ClickHouseClient(Settings())
print(release.materialize_market_sale_events(clickhouse=client, owner="rollout"))
print(release.materialize_market_rental_events(clickhouse=client, owner="rollout"))
```

If a check fails, read its value against the ledger before accepting anything. Accept a failure
only by its exact name and with a written reason (`accept={"days_lost": "<reason>"}`), as for the
11 April 2026 rentals day (`DLD_LEASE_DATE_CORRECTION.md`).

## 7. Views and caches

- `cd backend && uv run python -m scripts.clickhouse.create_compatibility_views`. It refuses a
  market table whose release predates the uniform columns.
- Flush the API cache (Redis `FLUSHDB` on the API's database).

## 8. Verify

```bash
cd backend
VERIFY_API_TOKEN=<token> VERIFY_API_URL=<api> uv run python -m scripts.clickhouse.verify_dxbi_transactions
VERIFY_API_TOKEN=<token> VERIFY_API_URL=<api> uv run python -m scripts.clickhouse.verify_analytics
cd ../e2e && PLAYWRIGHT_BASE_URL=<app> bunx playwright test transactions.spec.ts --project=chromium
```

Both scripts must end with 0 failures. Then compare a few areas against dxbinteract.com's summary
cards, as `TRANSACTIONS_DXBI_VALIDATION.md` records.

## 9. Paid checks (approval)

One end-to-end chat turn that asks for a market metric (for example "average villa rent in Arabian
Ranches over the last year": townhouses now count as villas), and one Feasibility generation.
