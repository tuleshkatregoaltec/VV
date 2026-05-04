# Bayut Listings

`bay_listings` captures listing search snapshots from the unofficial Bayut
RapidAPI API. These are listing snapshots, not transaction records.

## Source Contract

- Provider: `bayut`
- Dagster raw asset: `bay_listings_raw`
- Checkpoint strategy: `latest_pages`
- Cadence: daily
- Bronze table: `bay_listings_bronze`

## Raw Files

Files are emitted per purpose/category/location:

```text
bay_listings_<purpose>_<category>_location_<location_id>.jsonl
```

Rows include purpose, category, location id, page number, scraped timestamp, and
the raw listing payload.

## R2 Layout

```text
raw/source=bay_listings/extract_date=<date>/run_id=<run_id>/*.jsonl
raw/source=bay_listings/manifests/<run_id>.json
```

## Config Notes

Important knobs:

- `locations_ids`: Bayut location IDs to query. Default is Dubai.
- `purposes`: `for-sale`, `for-rent`.
- `categories`: default `residential`.
- `max_pages`: listing pages per query.
- `rent_frequency`: default `yearly`.

## Operational Notes

This source depends on RapidAPI quota and should stay conservative unless the
quota/cost profile is understood.
