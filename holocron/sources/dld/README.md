# DLD Transactions

`dld_transactions` extracts Dubai Land Department transaction JSON by day and
transaction kind.

## Source Contract

- Provider: `dld`
- Dagster raw asset: `dld_transactions_raw`
- Checkpoint strategy: `daily`
- Cadence: daily
- Bronze table: `dld_transactions_bronze`

## Raw Files

Transaction detail files:

```text
dld_transactions_<kind>_<day>.jsonl
```

Daily total files:

```text
dld_transaction_daily_totals_<day>.jsonl
```

`kind` is one of `sales`, `mortgage`, or `others`.

## R2 Layout

```text
raw/source=dld_transactions/extract_date=<date>/run_id=<run_id>/*.jsonl
raw/source=dld_transactions/manifests/<run_id>.json
```

## Config Notes

Important knobs:

- `mode`: `incremental` or `backfill`.
- `start_date`, `end_date`: required for backfill.
- `lookback_days`: incremental window.
- `transaction_kinds`: `sales`, `mortgage`, `others`.
- `data_mode`: `Flat` or `Aggregated`.
- `include_daily_totals`: include daily aggregate endpoints.

## Operational Notes

This source is naturally chunked by day. Backfills should prefer date windows
that are small enough to rerun cheaply if one day fails.
