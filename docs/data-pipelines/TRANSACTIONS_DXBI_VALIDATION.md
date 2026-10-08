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
| Both | Location | `area_name` | DXBI's commonest spelling of the same letters and digits; `X Dubai` becomes `X` when DXBI also names `X`; a unit marker (`No. 630`) is not a location. The Location *filter* groups by DXBI's own areas (below) |
| Both | Project (hidden by default) | `project_name` | as recorded (DXBI fills it on ~11% of rows) |
| Both | Property Type | `property_type` | DXBI's words |
| Both | Bedrooms | `bedrooms` | `Studio`, `1 Bed`, `2 Beds`, … (DXBI writes `2 Bed` and `2 Beds` for the same count) |
| Both | Size (sq ft) | `size_sqft` | DXBI's own square feet, shown in whole sq ft; no size is shown as `-` |
| Sales | Price (AED) | `sale_amount_aed` | as recorded |
| Sales | Price/sq ft (AED) | `price_per_sqft_aed` | DXBI's own price per sq ft, as DXBInteract shows it (for some villas DXBI divides by the built-up area, not the size it shows); price ÷ size only when DXBI gives none |
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

**Location: DXBI's own grouping (decision 2026-10-07).** The Location filter offers DXBI's areas,
sub-areas and master communities, and holds every record DXBI's area page for it counts. Those
pages can count a record under a different place than the area printed on its row. In August
2026, JVC's page counted buildings printed only "Al Barsha South 4", and Dubai Marina's page
counted 154 sales while 181 rows print "Dubai Marina". A JVC sale is also on the page of JVC's DLD
area, Al Barsha South Fourth. The Location column still shows the area DXBI prints on the row.

DXBI's rows carry no location id, so the grouping is learned by running DXBI's own search for each
location (`holocron/scripts/dxbi_location_sweep.py`, runbook
`holocron/docs/runbooks/dxbi-location-sweep.md`) into `dxbi_location_members`. A record takes, in
order:
1. the locations whose search returned it;
2. otherwise, the locations that returned other sales in its building (leases use this);
3. otherwise, the location named like its printed area, plus the areas above it.

For August 2026 the sweep returned exactly DXBI's card counts: JVC 761, Dubai Marina 154.

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
| Sales whose unit DXBI hides were dropped by the loader (audit leak L1) | 114,466 sales 2014–2026 (about 10% of DLD's count) | Loader fixed 2026-10-07: they load with an empty unit and show `-`; two such sales with the same date, building, price and size in one search stay two sales. They reach the page once the raw files are re-loaded or re-scraped |
| A buyer's agent's name glued to the building (`Hajar Binghatti Royale` for DXBI's `Binghatti Royale`): the row's text also holds names DXBI hides on screen | about 2% of sales since 2022 | Loader fixed 2026-10-07: the building and area come from the location DXBI shows (the `title` of the row's location). The loader then deletes the older copy of each re-loaded sale, so nothing counts a sale twice. Rows already loaded keep the glued names until re-loaded |
| Same place spelled two ways | 5 names (`City of Arabia`, `Dubai islands`, `Dubai Land`, `Al Yufrah1`, `Jumeirah Village Circle Dubai`) | merged as above |
| Misspellings DXBI uses beside the right name | e.g. `Jumeirah Villlage Circle` (4 sales), `Al Barshaa South 2`, `Al Thanayah 4`, `Nad Al Shiba 1` / `Nad Al Sheba 1`; DXBI also uses both `Marsa Dubai` and `Dubai Marina` | not merged (would be a guess); they show as separate locations |
| Building names differing only in capitals | 3 (`Serenz by Danube - Tower B` / `TOWER B`, two `Raw District 2` names) | not merged |
| Implausible sizes | sales under 108 sq ft (10 m²): 289 apartments; leases under 108 sq ft: 8,253 apartments, 1,652 villas; leases over 53,800 sq ft (5,000 m²): 1,044 villas | the Transactions pages show them as DXBI does; the combined layer behind Analytics treats the small ones as having no size (see "Sizes no home can have" below) |
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

## Sizes no home can have (2026-10-07)

In the combined layer behind Analytics and the chatbot, apartments and hotel apartments under
108 sq ft (10 m²) and villas and townhouses under 500 sq ft have no size and no price per sq ft;
their price, rent, date and every other field are kept, and other types (offices, shops,
partitions) keep any size. The Transactions pages mirror DXBInteract and show DXBI's own size and
price per sq ft for every record (decision 2026-10-07, after the reconciliation below).

What these sizes are, measured on the local copy:

- **A placeholder.** DLD's rent register records 1 m² on 139,381 apartment and 45,456 villa leases
  before 2025. DXBI shows the same placeholder converted, 11 sq ft (1 m² = 10.76 sq ft), on 18,394
  leases; other leases of the same units are ~1,100 sq ft at the same rent. These are not square
  metres to convert: the true size is unknown.
- **Hotel-room registrations.** Both DLD and DXBI list most Ciel studios at ~9 m² (~90 sq ft) and
  some Sky Bay Hotel and The First Collection rooms at 9-14 m², while other rooms in the same
  buildings are 300-400 sq ft.
- **Part shares.** A few hundred sales of a share of a unit, where price and size are both a
  fraction.
- About 350 leases look like m² typed as sq ft (×10.76 matches another lease of the same unit);
  they fall under the floor and show no size.

Effect, last 12 months, combined layer (projected on the served rows; rebuilding the layer can also
fill a placeholder with DLD's real size for the same lease): average rent per sq ft 167 → 90 AED
for apartments and 647 → 69 AED for villas; by area, for example, Al Nahda 2 545 → 55 and Mirdif
520 → 50. Medians barely move (apartments 78 → 77). Sales move little (hotel apartments 2,578 →
2,500); Ciel itself trades at ~6,000 AED/sq ft even for its 300-400 sq ft rooms.

The rule is `MIN_HOME_SQFT` in `holocron/holocron/market/transforms.py`.

## Reconciled against dxbinteract.com (2026-10-07)

Signed in to DXBInteract and compared its own figures with the local copy (read-only, ~40 page
views). The local copy's DXBI sales end on 19 September 2026 and its leases on 20 September, so
periods end before that.

**Totals.** DXBI's summary cards (all types, sale date) against the Sales page:

| Area, period | DXBI sales | Page | Median price DXBI / page | Median AED/sq ft DXBI / page |
|---|---:|---:|---|---|
| Business Bay, 1 Jan – 18 Sep 2026 | 4,829 | 4,781 | 2,264,000 / 2,250,000 | 2,490 / 2,478 |
| Business Bay, 1 – 18 Sep 2026 | 285 | 292 | 2,000,000 / 2,000,000 | 2,190 / 2,182 |
| Downtown Dubai, 1 Jan – 18 Sep 2026 | 1,598 | 1,505 | 3,150,000 / 3,150,000 | 2,830 / 2,903 |
| Downtown Dubai, August 2026 | 163 | 142 | 3,130,000 / 3,100,000 | 2,560 / 2,705 |
| Jumeirah Village Circle, 1 Jan – 18 Sep 2026 | 7,560 | 6,917 | 1,025,000 / 1,012,000 | 1,470 / 1,441 |
| Dubai Marina, 1 Jan – 18 Sep 2026 | 1,542 | 1,630 | 1,850,000 / 1,990,000 | 2,000 / 1,976 |
| Palm Jumeirah, 2025 | 1,693 | 1,539 | 5,000,000 / 5,062,000 | 3,190 / 3,217 |
| Dubai South, July 2026 | 2,371 | 2,342 | 730,000 / 730,000 | 1,700 / 1,699 |

DXBI's rental cards ("Avg. annual rent" is a median; it equals the page's median exactly in 11 of
12 cases): Business Bay June 2026 new 1,128 / renewed 854 against the page's 1,211 / 910 before
the fix below; Jumeirah Village Circle June 1,382 / 942 against 1,570 / 971.

**Row by row.** Every DXBI row of a search was read and matched to the page by DXBI link (or
building, date and price for CSV-loaded rows):

- JVC sales 19 – 30 June 2026 (299 DXBI rows): every matched row agrees on unit, date, price,
  size, price per sq ft, bedrooms, status and type. 23 of DXBI's rows are on the page under the
  area DXBI prints on the row ("Al Barsha South 4", or none for villas listed by community): DXBI's
  area search groups by its own location id, the page by the printed area. 1 sale was not loaded.
- Downtown Dubai sales August 2026 (163 DXBI rows): 117 matched with identical price, date,
  status and type (size and price per sq ft differ on 1 row DXBI has since corrected). 46 sales are
  missing: 11 and 18 August are absent or partial, and 1 – 10 August exist only as CSV-export
  rows, which carry no unit number and whose date is a day off DXBI's for a third of them.
  29 rows have no bedroom count where DXBI now shows one (DXBI added it after the scrape).
- Business Bay leases 25 – 30 June 2026 (300 DXBI rows): 297 matched; rent and dates agree;
  size differs on 3, bedrooms are empty on 11 where DXBI now shows them, and DXBI has renamed
  34 buildings since the scrape ("Peninsula Five -3" is now "Peninsula Five Tower 3").

**Fixed after the reconciliation.** Price per sq ft is DXBI's own figure (it differed on 2,564
villa sales a year, where DXBI divides by the built-up area); sizes are shown exactly as DXBI shows
them; a lease DXBI lists both with and without its unit is counted once (90 of Business Bay's
2,121 June leases were such copies; the page's June totals are now 2,031 against DXBI's 1,982 in
Business Bay and 2,307 against 2,324 in JVC).

**Not fixable in the page.** Gaps that need the loader or a re-scrape: sales after 19 September
2026; 11 and 18 August; August's CSV-only rows (no unit, some dates a day off); sales whose unit
DXBI hides when they are scraped (the loader keeps them since 2026-10-07; the rows already loaded
predate that); bedroom counts and building names DXBI improved after the scrape. Area totals also
differ because DXBI's area search uses its own location ids. DXBI's report rows carry no location
id of their own (none in the sales row HTML read on 2026-10-07, none in the stored row attributes
of 1.6M leases); the only id is the one the scraper searches with, which is Dubai for the full
sweep. Grouping by DXBI's areas needs a search per area that records which area each building
falls in.
