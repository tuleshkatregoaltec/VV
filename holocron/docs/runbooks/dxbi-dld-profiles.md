# DXBI records completed from DLD

Every DXBI sale and lease gets one profile row (`dxbi_sale_profile`, `dxbi_rental_profile`):
the location chain **Area → Master Project → Project → Building → Unit**, property type,
bedrooms and completion status (Off-Plan / Ready). Each value carries its source in a
`*_source` column. Transactions shows DXBI's own values first and fills only what DXBI left
empty; it also shows DLD's master project and official area.

## How a DXBI row finds its DLD record

DLD publishes no building name, no unit number and, since 2026, no property id, parcel id or
Ejari contract number. A DXBI row is matched by what both sides record:

- **Sales** (`market_sale_matches`): the same price, to the dirham (±1 for rows loaded before
  prices were rounded), within 3 days, or within 30 days with the same size (±1%). Pairing is
  one-to-one and runs in rounds, so a launch day's identical sales all pair. Leftovers then pair
  on the same price and the same size to the sq ft, up to a year apart (older DXBI dates run
  weeks ahead of DLD's registration).
- **Leases** (`market_rental_matches`): the same dates and amount, annual amount or size inside
  the lease's DLD area (tiers 0-3). Then a lease whose dates, amount and size are unique on both
  sides (tier 4) and the remaining keys (tiers 5-8) pair in other DLD areas only where the DXBI
  area is evidenced to lie (same place spelled differently, a DLD project of that name in the
  area, or the area's matched sales).

Rows without a one-to-one pair still get a profile: from the best DLD sale at the same price,
date and size (`dld_evidence`), the agreement of the same DXBI building's paired sales
(`building`), the project's master project (`project`), a DXBI sale of the same unit
(`dxbi_sale`) or DLD's unit register (`dld_unit`). A building no source places in a project is
its own project (`own_building`, as DLD registers standalone towers: "HDS Tower"). A DXBI
"building" that is the name of an area or master project DLD or DXBI knows ("Jumeirah Village
Circle (JVC)", "Mirdif": villas and plots listed under their community) is `place_name`; that
fill stays in the profile and is not copied into the market tables, so Analytics lists no
project no source names.

## Location, map link and the master-project dictionary

`location` joins Unit, Building, Project, Master Project and Area (each once, DLD capitals in
title case) and ends in "Dubai"; `map_url` opens the building's coordinates (PropertyFinder tower
or DXBI's building list) or, without them, a Google Maps search for the place. Transactions shows
it as its one Location column.

Master projects come, in order, from DLD's record, DLD's other registrations of the project,
`holocron/market/data/master_project_overrides.csv` (web-verified, one source URL per row; add a
row when a new launch has no master anywhere), DXBI's own community, PropertyFinder's community,
an area DLD renamed after its community in 2026 ("JUMEIRAH VILLAGE CIRCLE"), and the master DLD
uses for nearly all of the area. A DLD spelling of the master is kept, so Analytics lists it once.
The market tables take a profile's project and master project wherever their own row has none,
and DLD-only rows take the master the profiles found for their project.

## What is not filled, and why

- Leases in areas DLD organises without projects (Al Barsha 1, Karama, Al Qusais, ...): DXBI
  gives only the area and DLD has no project or building name there. The lease profile carries
  DLD's building reference (`dld_building_ref`: land / building number) and floor instead.
- DXBI leases DLD's open data does not publish (business-centre offices in Al Khabeesi, Al
  Garhoud, ...: DXBI lists about three times DLD's count there) and DXBI rows listed twice.
- DLD stopped filling master project in 2026 open data; it is filled from the project's other
  registrations where they exist.

## Agents' names in DXBI building names (stop-gap)

DXBI's row text holds the buyer's or seller's agent, hidden on screen, right before the building.
The July 2026 scrapes (`dxbi_sales_dynamic_2026-07-08..10`) were parsed from that text, so
14,056 of their sales carry the agent in front of the building ("Sheetal Lakeshore Tower 1"). The
loader reads DXBI's location title since commit d406840, and loads of the current scraper have
none; the July raw text cannot be re-parsed.

**The fix is to re-scrape those sales** (dates 2016 to June 2026; every one keeps its DXBI detail
URL) with the current scraper, then delete `holocron/sources/dxbi/agent_names.py` and its call in
`load_dxbi_sales_units.py`. Until then `repair_agent_names` runs after every sales load: it
removes a leading prefix only on evidence (the rest is a building DXBI lists at least three times
as often in the area, and the prefix reads as a person), records each repair with the sales it
changed in `dxbi_building_name_repairs`, and rewrites them. A review that finds a raw name is a
real building inserts a newer row of it whose `building_name` is the raw name (rule `reviewed`);
the next run gives the changed sales their name back.

An LLM check with web search was tried on the 409 weaker repairs on 2026-10-13 (one-word prefixes
whose word occurs in a place name, and the rules that lean on earlier repairs): 363 were agents
with a page naming the rest, 45 unsure and none a real building, so it was not kept.

After a repair: build the profiles, then the releases (sales, then rentals), then the profiles
again; a release built from older profiles brings the old names back through the project fill.

## Schedules (Dagster)

- `dld_od_*_daily_incremental` (04:00-05:30 Dubai): re-reads 7 days after the last loaded
  window.
- `dld_od_transactions_weekly_resweep` (Sunday 03:00): re-reads 90 days. DLD backdates weekend
  registrations; 2.2% of sales (21 Jul - 30 Aug 2026), nearly all on Saturdays and Sundays, were
  missing from loads that re-read only the last days. **Ships stopped like every provider
  schedule: turn it on in the Dagster instance that runs the DLD jobs.**
- `market_events_refresh` (10:30): the sales and lease releases, then `dxbi_profiles`.

## By hand

```bash
python -c "from holocron.platform.clickhouse import ClickHouseClient; from holocron.platform.settings import Settings; from holocron.market.release import materialize_market_sale_events as s, materialize_market_rental_events as r; c = ClickHouseClient(Settings()); print(s(clickhouse=c)); print(r(clickhouse=c))"
python scripts/build_dxbi_profiles.py
```

The sales release computes its match candidates once into `market_sale_pair_candidates__work`
and the rentals release its area evidence into `market_rental_area_sets__work`; each release
drops its work table at the end (a failed one leaves it for the next release to replace).

A release that pairs more DXBI rows serves fewer DLD rows (the DLD copy of a paired DXBI sale
is no longer shown beside it) and can trip the `served_rows` check; accept it by name with a
reason only after comparing match statuses against `market_sale_events__previous`.
