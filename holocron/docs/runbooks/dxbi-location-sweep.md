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
