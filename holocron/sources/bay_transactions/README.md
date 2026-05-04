# Bayut Transactions

`bay_transactions` captures transaction snapshots from the unofficial Bayut
RapidAPI API across Dubai community IDs. It is useful as a supplementary
transaction source, but quota and endpoint caps should be treated carefully.

## Source Contract

- Provider: `bayut`
- Dagster raw asset: `bay_transactions_raw`
- Checkpoint strategy: `date_window`
- Cadence: daily
- Bronze table: `bay_transactions_bronze`

## Raw Files

Files are emitted per purpose/date window:

```text
bay_transactions_<purpose>_<start_date>_<end_date>.jsonl
```

Rows include purpose, date window, request body, page number, locations queried,
and the raw transaction payload.

## R2 Layout

```text
raw/source=bay_transactions/extract_date=<date>/run_id=<run_id>/*.jsonl
raw/source=bay_transactions/manifests/<run_id>.json
```

## Config Notes

Important knobs:

- `mode`: `incremental` or `backfill`.
- `start_date`, `end_date`: required for backfill.
- `lookback_days`: incremental window.
- `purposes`: `for-sale`, `for-rent`.
- `locations_ids`: Dubai community IDs.
- `location_batch_size`: defaults to 1 to reduce response ambiguity.
- `max_pages`: pages per request.

## Operational Notes

Keep this source conservative. Prefer small date windows and low page counts
until quota and endpoint completeness are verified.
