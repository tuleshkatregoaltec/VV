# Re-scrape (or re-load) the July 2026 DXBI sales batch

Goal: every DXBI sale shows the building DXBInteract shows, taken from DXBI's own data, so that
the agent-name stop-gap (`holocron/sources/dxbi/agent_names.py`) can be deleted.

## The problem

- The July 2026 batch is 81 files, `dxbi_sales_dynamic_2026-07-08..11*.jsonl`, written by
  `scripts/dxbi_sales_dynamic_bucket_runner.js`. They hold 952,885 sales dated 2014-01-02 to
  2026-06-30. The raw files are not on the dev machine or in object storage: they are on the Mac
  (`/Users/eier/VV/DXBI-Backfill/sales-dynamic`) or ph-box (`/root/data/dxbi-daily`).
- DXBI's sales row holds, hidden on screen, the buyer's or seller's agent right before the
  building. The batch was loaded on 2026-07-28 by a parser that read the row's text, so some
  buildings carry the agent's name ("Sheetal Lakeshore Tower 1"). The loader reads the title of
  the location cell since commit d406840 (2026-10-07), which is what DXBI shows. Loads since then
  are clean: 0 of 40,893 sales from 2026-07-01 on start with a known agent name.
- 14,056 sales of the batch are repaired by the stop-gap today; 14,054 of them are dated 2021 or
  later. The stop-gap catches only names its rules recognise, and some remain: for example, 31
  sales still carry a brokerage's name ("Luiza TOP PRIORITY Real Estate LLC Al Habtoor Tower"),
  all of them from the batch (2026-10-14).

| Sale year | Sales in the batch | Repaired by the stop-gap |
|---|---|---|
| 2014-2020 | 232,943 | 2 |
| 2021 | 46,175 | 220 |
| 2022 | 95,065 | 1,117 |
| 2023 | 127,069 | 2,523 |
| 2024 | 165,230 | 3,077 |
| 2025 | 200,673 | 4,870 |
| 2026 (to 30 Jun) | 85,730 | 2,247 |

A sale's key is a hash of its DXBI detail URL. DXBI's detail URLs are stable: the October
location sweep returned 223,536 rows whose keys are July-batch sales. So a re-load or a
re-scrape gives the same sales the same keys and replaces their July versions in place; the
Transactions Location filter (`dxbi_location_members`) stays linked.

## Step 1 — check the raw files (no DXBI traffic)

The runner saved every cell's HTML (`columns[].html`). If the location cell's HTML holds its
title, re-loading the files with today's loader fixes every name. On the machine that has the
files, from a checkout of this repo:

```bash
cd holocron && uv run python scripts/check_dxbi_sales_titles.py /Users/eier/VV/DXBI-Backfill/sales-dynamic/dxbi_sales_dynamic_2026-07-*.jsonl
```

It prints, per file, the sales, how many have DXBI's title and how many buildings a re-load would
change. Nothing is written. Exit code 0 means every sale has a title.

- **Every sale has a title:** go to step 2A.
- **Some files have no titles** (the HTML was cut off or not saved): go to step 2B for the dates
  of those files only, and do step 2A for the rest.

## Step 2A — re-load the files (preferred)

Load into the production warehouse with its credentials in the environment (as the evidence
loader does), one batch at a time:

```bash
cd holocron && CLICKHOUSE_HOST=… CLICKHOUSE_USER=… CLICKHOUSE_PASSWORD=… CLICKHOUSE_DATABASE=vitevue uv run python scripts/load_dxbi_sales_units.py /Users/eier/VV/DXBI-Backfill/sales-dynamic/dxbi_sales_dynamic_2026-07-*.jsonl
```

- No `--replace-window`: the files are the same rows, so the loader's superseded step deletes
  each sale's older version (the building is part of the sort key).
- Expect `loaded` ≈ 952,885, `superseded` ≈ the number of changed buildings that step 1 printed,
  `errors=0`. With errors the loader stops before any delete; fix and re-run.
- Archive the 81 files to object storage (`raw/source=dxbi_evidence/…`, as
  `holocron/sources/dxbi/evidence.py` does for runs), so history can be replayed without the Mac.
  This also closes audit gap L13.

## Step 2B — re-scrape the dates (only where step 1 failed)

Use the maintained sales scraper, `scripts/dxbi_rental_backfill.py --report sales`, as the daily
timer does (`deploy/systemd/dxbi-report-daily.sh`), on ph-box with account A. It writes run
directories with `reconciliation.json`, and Holocron's evidence loader then loads each completed
run with `--replace-window`, so DXBI's current listing replaces those dates outright (including
sales DXBI has since moved to another day or dropped).

- **Scope:** 2021-01-01 to 2026-06-30, where the agent names are (14,054 of 14,056). Do
  2014-2020 only if step 1 found untitled files there.
- **Chunks:** one run per calendar quarter (22 runs), newest first, back to back. Take the shared
  lock so a run never overlaps the daily scrape:

```bash
flock /run/lock/vitevue-dxbi-sales.lock /root/repos/vitevue-platform/holocron/.venv/bin/python /root/repos/vitevue-platform/holocron/scripts/dxbi_rental_backfill.py --report sales --credentials /root/.config/vitevue/dxbi/account-a.json --storage-state /root/.config/vitevue/dxbi/account-a-state.json --browser /root/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome --account-id account-a --direction desc --delay-min 2 --delay-max 4 --template-date 2026-06-30 --start-date 2026-04-01 --end-date 2026-06-30 --run-id rescrape-2026Q2 --output-dir /root/data/dxbi-daily/sales/run=2026-10-15-rescrape-2026Q2
```

- **Failed days:** DXBI's Cloudflare returns 520/522 at times. A run with failed days has no
  `_SUCCESS`; re-run the same command (same output directory) and only those days are retried.
  Nothing is loaded until the run is complete.
- **Size:** 719,942 DXBI sales in scope (2021 to June 2026), at most a few pages per day plus the per-day setup,
  paced 2-4 s per request. Allow 1-3 days of wall time for the 22 runs, outside the daily
  22:30 UTC sales slot.
- **Load:** the runs land in `DXBI_EVIDENCE_DIR/sales/`; the evidence asset archives and loads
  each one (or run `load_dxbi_sales_units.py --replace-window FIRST LAST <run dir>` by hand, one
  run at a time, oldest first).

## Step 3 — check the result

All on the production warehouse.

1. No sale in scope still comes from the July files (2B), or every July sale was reloaded (2A):

```sql
SELECT count() FROM dxbi_sales_unit_events FINAL
WHERE startsWith(source_file, 'dxbi_sales_dynamic_2026-07') AND transaction_date >= '2021-01-01'
```

   After 2B this is 0. After 2A the sales keep their file names; check instead that
   `superseded` matched step 1.
2. The stop-gap finds nothing new, and no raw agent-prefixed name is left in the sales:

```sql
SELECT count() FROM dxbi_building_name_repairs WHERE built_at > '<load start>';
SELECT count() FROM dxbi_sales_unit_events FINAL
WHERE (lowerUTF8(area_name), building_name) IN (SELECT area_key, raw_building_name FROM dxbi_building_name_repairs)
```

   Both must be 0. For 20 sales the stop-gap had repaired (`arrayJoin(sale_keys)`), the building
   now equals the repair's clean name, or differs only where DXBI names it otherwise.
3. Sales per month in scope, before and after: within 2%, or explained (DXBI adds late
   registrations and drops duplicates). Write the month table into the PR that retires the
   stop-gap.
4. Rebuild the market layer: run `market_events_refresh` twice (each run does the releases, then
   `dxbi_profiles`); every release check must pass.
5. Analytics, in the browser: Lake Shore Tower, Sky Courts, Dubai Marina (master) and JVC show the
   same totals as direct SQL on `ch_transactions`, with no agent name in any building search
   result.

## Step 4 — retire the stop-gap

Once step 3 passes, open a PR that:

- deletes `holocron/sources/dxbi/agent_names.py`, its call in `scripts/load_dxbi_sales_units.py`,
  its use in `holocron/assets/geography.py` (`UNSERVED_NAMES_SQL`) and
  `tests/test_dxbi_agent_names.py` (keep the `check_dxbi_sales_titles.py` test);
- removes the "Agents' names" section of `dxbi-dld-profiles.md`;
- keeps `dxbi_building_name_repairs` for 30 days as the audit trail, then drops it.

## Who does what

| Step | Where | Needs |
|---|---|---|
| 1, 2A | the Mac or ph-box (where the files are) | a repo checkout with `uv`; production ClickHouse credentials for 2A |
| 2B | ph-box | DXBI account A (as the daily timer), the shared sales lock |
| 3, 4 | anywhere with warehouse access | — |
