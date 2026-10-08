# Transactions pages: DXBI-only data, validated

Date: 2026-10-06 (units: square feet throughout, see the section at the end). Measured on the local warehouse copy (handoff snapshot): DXBI sales run to
2026-09-19 and DXBI leases start up to 2026-09-20, so "Last Week" shows no sales locally. Re-run
`backend/scripts/clickhouse/verify_dxbi_transactions.py` on staging and production after deployment.

## Decision

The Transactions pages (Sales and Rentals) show DXBInteract (DXBI) records only: every row and
every value comes from Holocron's `dxbi_sales_unit_events` and `dxbi_rental_events`. No DLD row
and no DLD-filled value is shown. The Analytics pages and the chat keep the combined DXBI + DLD
market layer (`ch_transactions` / `ch_rent_contracts`), so the two areas no longer show the same
counts (see "Transactions versus Analytics").

## What each column is

| Page | Column | DXBI source | Rule |
|---|---|---|---|
| Sales | Date | `transaction_date` | DXBI's sale date |
| Sales | Unit | `unit_number` | as DXBI records it (new column) |
| Both | Building | `building_name` | as recorded |
| Both | Location | `area_name` | DXBI's commonest spelling of the same letters and digits; `X Dubai` becomes `X` when DXBI also names `X`; a unit marker (`No. 630`) is not a location |
| Both | Project (hidden by default) | `project_name` | as recorded (DXBI fills it on ~11% of rows) |
| Both | Property Type | `property_type` | DXBI's words |
| Both | Bedrooms | `bedrooms` | `Studio`, `1 Bed`, `2 Beds`, … (DXBI writes `2 Bed` and `2 Beds` for the same count) |
| Both | Size (sq ft) | `size_sqft` | DXBI's own square feet, shown in whole sq ft; no size is shown as `-` |
| Sales | Price (AED) | `sale_amount_aed` | as recorded |
| Sales | Price/sq ft (AED) | — | price ÷ size in sq ft, rounded to whole AED (matches DXBI's own price per sq ft on 98% of sales) |
| Sales | Status | `market_status` | `Off-Plan` / `Ready` |
| Rentals | Start / End Date | `lease_start`, `lease_end` | the page is dated by lease start |
| Rentals | Unit | `unit_number` | new column |
| Rentals | Annual Rent (AED) | `annual_rent_aed` | contract amount × 12 ÷ term in months (checked on every row) |
| Rentals | Contract Amount (AED), Term (months) (hidden by default) | `contract_amount_aed`, `contract_term_months` | as recorded |
| Rentals | Contract Type | `contract_state` | `New` / `Renewed` |

Removed because DXBI does not hold them: Group, Procedure, Sub Type, Landmark, Nearest Metro,
Nearest Mall (sales); Sub Type, Tenant Type, # Properties, Freehold, Landmark, Nearest Metro,
Nearest Mall (rentals). The DLD project selector is replaced by DXBI Location and Building filters.
The details popup no longer offers "Find Matching Unit": it called an endpoint that does not exist,
and DXBI records the unit.

**Residential / Commercial / All.** DXBI gives a property type but no usage. Residential is
Apartment, Villa, Townhouse and Hotel Apartment; Commercial is Office, Shop, Show Rooms, Warehouse,
Workshop, Clinic, Gymnasium, Hotel, Sized Partition, Building and Commercial. Plots and rows DXBI
gives no type appear under the new **All** option only.

**Periods.** "Last N days" is the last N calendar days, today included; leases that start in the
future are not shown until they start.

**Bands.** Size (sq ft), price, price per sq ft and rent bands are half-open: `1,000-2,000` is
1,000 up to (not including) 2,000 and `5,000+` is 5,000 and above. Before, a unit on a boundary
counted in two bands. The bands' totals now add up exactly to the rows that have a value.

**Filter options.** Building lists every building in the filtered rows (it stopped at the first
1,000 alphabetically, so most buildings could not be chosen).

## One row per sale or lease

DXBI's tables need de-duplication before display. Last 365 days:

| Dataset | Raw rows | Shown | Removed | Why |
|---|---:|---:|---:|---|
| Sales | 169,439 | 168,154 | 1,270 | older versions of a sale whose address was re-normalised (the latest load wins). Across all dates, 144 sales are listed twice by DXBI in one scrape with conflicting details: the more complete listing wins (location, bedrooms, status present, then the shorter building name, which drops a glued-on agent name) |
| | | | 15 | one real unit sold the same day at the same price, loaded twice (CSV export without a DXBI link + scrape) |
| Rentals | 850,230 | 841,108 | 9,122 | a numbered unit's identical lease repeated by the report while paging (same unit, dates, amount, state and raw fingerprint) |

Identical lease rows **without** a unit number are all kept: they cannot be told apart from
several units let on the same terms. A unit "number" without digits (`D`) does not identify a
unit, so such sales are never merged.

## Verification

1. **Independent recomputation** (`verify_dxbi_transactions.py`): the last 365 days are rebuilt
   in pandas from the raw DXBI tables with every rule re-implemented (no backend SQL reused) and
   compared with the live API (sizes in sq ft, prices per sq ft): totals and the first, a middle
   and the last page for 7, 30, 90,
   180 and 365 days × Residential / Commercial / All; every field of every compared row; one page
   per property type, bedroom count, status and contract type, the 8 largest locations and 4
   largest buildings; every band of size, price, price per sq ft and rent, and that each band
   family adds up to the rows with a value; the filter options. **358 checks, 0 failures**
   (522 in the exploratory run, which also counted passes per page).
2. **The pages in a browser** (headless Chromium against the running app): the displayed count
   equals the API total, and every cell of every row equals the API value in the page's format,
   for the default views, filters chosen through the controls (type, size band, location +
   bedrooms + price-per-area band, rent band + contract type), page 2, Commercial (no bedrooms column
   or filter), All over the last year, plots, the optional Project / Contract Amount / Term
   columns, the details popup, and the CSV export (same rows, same order, 50,000-row cap).
   **53 checks, 0 failures**, no page errors. Every shown annual rent equals contract amount × 12 ÷
   term.
3. **Automated tests**: real-ClickHouse tests with the production DDL for the de-duplication,
   unit conversion, bands, period edges, usage grouping, location spelling, options and exports
   (`backend/tests/integration/clickhouse/test_transactions.py`); unit tests for options, exports
   and the page helpers. Backend 340 unit + 38 ClickHouse + 15 Postgres, frontend 72, Holocron 523,
   all passing; type checks and linters clean.
4. **Speed** (no cache): 0.1–0.3 s for the default month views, up to 1.2 s for a full year of
   every record; responses are then cached for 10 minutes.

## Transactions versus Analytics

Residential, same periods:

| | Transactions (DXBI only) | Analytics layer (DXBI + DLD) |
|---|---:|---:|
| Sales, last 30 days | 4,934 | 5,055 |
| Sales, last 365 days | 158,548 | 168,509 |
| Rentals, last 30 days | 16,957 | 31,740 |
| Rentals, last 365 days | 563,287 | 654,266 |

The combined layer adds the records only DLD holds (15,871 sales and 178,783 leases in the year)
and hides DXBI records it judges to be copies of a DLD record, so the difference is not a single
number. DXBI holds about half of the most recent month's leases.

## DXBI data issues found

| Issue | Size (last 365 days unless stated) | Handling |
|---|---|---|
| 2026 plot sales misread by the loader (`Al Jafliya Plot, Floor u-hidden, No. 630`: the plot number became the area, the type was lost) | 256 sales | Loader fixed (`holocron/sources/dxbi/sales_units.py`, tested); rows already loaded show no location or type until they are re-ingested |
| Same place spelled two ways | 5 names (`City of Arabia`, `Dubai islands`, `Dubai Land`, `Al Yufrah1`, `Jumeirah Village Circle Dubai`) | merged as above |
| Misspellings DXBI uses beside the right name | e.g. `Jumeirah Villlage Circle` (4 sales), `Al Barshaa South 2`, `Al Thanayah 4`, `Nad Al Shiba 1` / `Nad Al Sheba 1`; DXBI also uses both `Marsa Dubai` and `Dubai Marina` | not merged (would be a guess); they show as separate locations |
| Building names differing only in capitals | 3 (`Serenz by Danube - Tower B` / `TOWER B`, two `Raw District 2` names) | not merged |
| Implausible sizes | sales under 108 sq ft (10 m²): 289 apartments; leases under 108 sq ft: 8,253 apartments, 1,652 villas; leases over 53,800 sq ft (5,000 m²): 1,044 villas | shown as DXBI records them; their price per sq ft is therefore extreme. Recommendation: treat sizes under 108 sq ft as missing on the page |
| DXBI's own price per sq ft uses built-up area for some villas | 3,235 villas | the page divides by DXBI's size, so for these villas its price per sq ft differs from DXBI's listing |
| Missing values | sales: project 89%, unit 2%; leases: building 66%, project 88%, bedrooms 34%, unit 7% | shown as `-` |

## Units: square feet everywhere (2026-10-06)

Every area the product shows is in square feet and every price or rent per area in AED per sq ft
(one factor, 10.7639 sq ft per m², `backend/app/market/units.py` and `frontend/src/lib/utils/units.ts`).
The Transactions pages use DXBI's own sq ft without conversion. The warehouse keeps its stored
units and the feasibility workbook keeps its model in m²; both convert where the product reads or
shows them. After the change the verifier above passed again (358 checks, 0 failures), and a browser
sweep of every page (Dashboard, Transactions, Analytics, Radar, Projects, Upcoming, Developers,
Listings, CRM, Profile, and every Feasibility sheet on a fixture study) found no square-metre text.
