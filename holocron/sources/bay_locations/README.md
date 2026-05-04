# Bayut Locations

`bay_locations` discovers Dubai location/filter IDs from the unofficial Bayut
RapidAPI API. The output is raw lookup data used to plan Bayut listing and
transaction queries.

## Source Contract

- Provider: `bayut`
- Dagster raw asset: `bay_locations_raw`
- Checkpoint strategy: `full_refresh`
- Cadence: weekly/manual full refresh
- Bronze table: `bay_locations_bronze`

## Raw Files

- `bay_locations_dubai.jsonl`

Each row represents a discovered location/search result with query/page context,
language, parent/ancestor data where available, and the source raw payload.

## R2 Layout

```text
raw/source=bay_locations/extract_date=<date>/run_id=<run_id>/bay_locations_dubai.jsonl
raw/source=bay_locations/manifests/<run_id>.json
```

## Config Notes

Important knobs:

- `queries`: search terms used to discover locations.
- `max_pages`: pages per query.
- `only_dubai`: filters output to Dubai-oriented locations.
- `include_ancestors`: enriches rows with ancestor context.
- `stop_after_pages_without_new`: stops broad searches once pages stop adding new IDs.

## Operational Notes

This is a bounded full refresh and should be small compared with listing or
transaction scrapes. It is safe to rerun when planning filters need refreshing.
