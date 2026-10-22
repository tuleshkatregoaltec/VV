# Analytics hierarchy: implementation plan

Status: implemented on the local warehouse, 21 Oct 2026 (branch `feat/dxbi-dld-complete-match`, #46),
with the unit-count work below (section 6). Open items: the review of the wrong-project records
(decision 3) and the unit counts DLD and the records disagree on
(`~/vv/analytics-hierarchy-audit-2026-10-21/unit_count_gaps.md`).
Findings this plan fixes: <https://claude.ai/artifact/LmJZ2HYpFQ29yL7nT2N8Qs> (audit) and
`~/vv/analytics-hierarchy-audit-2026-10-21/wrong_project_records.md` (wrong-project records).

## Decisions

| # | Decision | Source |
|---|---|---|
| 1 | One spelling per name: DXBI's spelling wins where DXBI has the name; otherwise DLD's, title-cased. | User, 21 Oct |
| 2 | DLD sub-communities fold into the community master: the 20 `DUBAI HILLS - …` masters into Dubai Hills Estate; `Springs - N`, `Meadows N` and `Lakes - …` into The Springs, The Meadows and The Lakes. Each sub-community stays a project. | User, 21 Oct |
| 3 | Records filed under another project than their building's are **not re-filed**. They are listed with their cause in `wrong_project_records.md` for review; each listed record carries a `stray` flag so a re-file is one switch later. | User, 21 Oct |
| 4 | Merges need evidence. Exact duplicates (case, spacing, punctuation) merge automatically. A near duplicate merges only when the records show it: shared buildings, the same DLD building, or a DLD register entry. Otherwise the names stay apart. | Plan |
| 5 | Unit counts name their source. Order: DXBI's building list, then DLD's unit register (by building, matched by unit numbers; or by project), then DLD's land register (villa plots). A count below the units actually traded is not shown; the page shows "at least N units traded" instead. | Plan |

## What changes

### 1. Holocron: a canonical hierarchy, built after the profiles

New module `holocron/market/analytics_hierarchy.py`, run by `build_profiles` and `build_listed`
between the profiles and the listed tables. Every table is built in staging and swapped in, as the
profiles are.

| Table | One row per | Holds |
|---|---|---|
| `analytics_project_keys` | spelling seen (name key) | the canonical project key it belongs to |
| `analytics_projects` | project | display name (rule 1), kind (Project / Building), the one master (rule 2), DLD area, record counts |
| `analytics_building_keys` | DXBI building name + community (+ project when the name is shared) | the building id it belongs to |
| `analytics_buildings` | building | display name, project, master, records, the DLD building it matches (unit numbers) |
| `analytics_unit_stock` | project and building | units and their source, units traded, buildings, unit mix by bedrooms (DLD register), median size |

Rules:

- **Name key**: lower case, letters and digits only. `MERANO TOWER` = `Merano Tower`,
  `INDIGO VILLE5` = `Indigo Ville 5`, `PARK VILLA\'S 2` = `Park Villas 2`.
- **Project display name**: DXBI's most used spelling for the key (its project, building and
  location-tree labels), else DLD's name in title case when DLD wrote it in capitals.
- **Project master**: the most common master over the project's records after
  `master_aliases.csv` (spellings, sub-communities, projects used as masters), unless
  `project_masters.csv` names it with evidence (AMARANTA 2 → Villanova, not DLD's
  "Jumeriah Beach Residence - JBR"). Every record of a project shows that one master, so a
  project is never split across masters.
- **Master display name**: DXBI's location-tree spelling where DXBI has the master
  (Dubai Silicon Oasis, Jumeirah Lake Towers, Damac Hills 2), else DLD's in title case.
- **Building**: a DXBI building name in its community. A name whose records clearly sit in one
  project (>= 80% of >= 10) is one building of that project; a name shared by several projects
  ("Tower 2") is one building per project. Not buildings: place names ("Al Warsan Industrial"),
  DXBI project labels ("Binghatti Skyrise (all buildings)") and DLD plot references.
  Two names in one project that match the same DLD building by unit numbers are one building
  ("Merano" / "Merano Tower" if the units say so).
- **Project near-duplicates** (`project_aliases.csv`): only pairs with evidence, each row
  citing it.

### 2. Listed tables carry the canonical columns

`dxbi_sales_listed` / `dxbi_leases_listed` gain `scope_key`, `scope_name`, `scope_kind`,
`master_name`, `building_id`, `building_name_display`, `stray`. A record loaded after the last
hierarchy build still resolves through the key tables (its spelling's key).

### 3. Backend Analytics

- `analytics/dxbi.py` reads the canonical columns; the per-record master and scope expressions go.
- Search reads `analytics_projects` / `analytics_buildings` (no scan of 2.6M records per
  keystroke). A building result is a building scope: `filter_type=building`, `building_id`,
  with its project and master for the label.
- Every project endpoint (summary, trends, price distribution, compare) accepts
  `filter_type=building` + `building_id`.
- Header numbers:
  - Building: units (source), unit mix, DXBI card developer and completion.
  - Project: units (source), buildings, unit mix, and a table of its buildings with units,
    sales and leases.
  - Master: rollup of its projects (total units, projects, buildings, projects with unit data).
- Cache key prefixes bumped.

### 4. Frontend

- Selector: building rows read "Building · Project · Master" and select the building.
- Header: a breadcrumb Master › Project › Building with links up; units with their source;
  "at least N units traded" where no register covers the traded units.
- Project view: a Buildings table (units, sales, leases). Unit mix table from the stock table.
- Compare accepts buildings.

### 6. Unit counts where names and numbers disagree (21 Oct 2026, second pass)

- **A project DLD holds under another name, or under no project.** 1.53M of DLD's 2.35M register
  units carry no project name (most older towers). A project with no register units under its name
  is linked to the register group holding its unit numbers at the same floor areas (within 2%), in
  its DLD area (an area DLD renamed in 2026 matches its older areas through their master): the
  group's DLD project, or for unnamed units its DLD building. The group must hold >= 80% of the
  project's unit numbers, at least 5, more than any other group (twin towers tie and link
  neither), and no other DXBI project may hold it by name or claim it. Stored in
  `analytics_project_dld_keys`; the project's count, its buildings' DLD matching and the unit mix
  read it.
- **Towers that repeat unit numbers.** Where unit numbers alone spread over a project's DLD
  buildings, the numbers at the same floor area (within 2%) pick the building (same 80% / >= 3 rule).
- **One DLD building, one building.** A DLD building matched by two buildings that are not
  spellings of one (Shoreline's towers all matched Al Das, the one DLD files under the project)
  counts for neither (`analytics_buildings.dld_claims`). Before, each took its count.
- **One name in one project is one building**, whatever DXBI community its records carry
  ("Zaabeel 2" / "Zabeel 2", "Al Furjan" / "Jabal Ali 1"), unless they sit on different DLD
  buildings. Before, 280 such pairs were two buildings each, and a project adding up DXBI
  building cards counted them twice (Arabella 1,378 units, now 689).
- **Units traded are counted once.** One unit key for matching and counting: "FLAT 415",
  "Unit No. 415" and "415" are one; "A-0101" and "A101" are one. A shop, office or parking code
  counts as traded only where the project's register holds it. Buildings on one DLD building hold
  one set of unit numbers in the project's count.
- **Land plots** are counted across both land-register snapshots by area name, land number and
  sub-number (the snapshots tag one plot as area 505 / 0 and sub-number '0' / ''); Vardon is 692.
- **DLD's unit register** is read from the newest complete snapshot (>= 90% of the largest). A
  refresh was tried on 21 Oct: the gateway's `units` command answers 200 with no rows (unfiltered,
  by area, either sort) while `lands` answers; the May snapshot stays.

### 7. Trust DXBI's building (decision 3, 21 Oct 2026)

The user chose: a record whose DXBI building clearly belongs to one project (>= 80% of >= 10 of
its records) is filed under that project. Cause of most wrong-project records: DXBI names the
building but not the project, DLD names the project but not the unit or building, so a record's
project came from a DLD sale or lease of the same price and date. Sister phases launched at one
price list (Damac Lagoons Nice 1 / Nice 2: 500 DLD sales at AED 1,706,000 for 1,550 sqft in 2022)
then swap records.

- **Pairing checks the building.** Sales: among equally good DLD candidates, one in the DXBI
  building's project wins when the building's paired sales agree >= 80% (was 90%, so Nice 1 at
  84% never used it). Leases: a first pass pairs a lease only with a DLD contract of its
  building's project (same area, dates and rent), before the general pass.
- **Listed records follow the building.** `scope_key` / `scope_name` / master are the building's
  project; `stray = 1` marks a record re-filed because its pairing named another project.
- **DXBI-only buildings** ("Geepas Tower", own-building scopes) are linked to the DLD building
  holding their unit numbers at the same floor areas, as projects are (section 6).
- **Unit key** drops Damac's estate prefixes ("DH2-XR1139B" = "XR1139B", "DL-K138" = "K138").

| | Before | After |
|---|---:|---:|
| Records whose pairing named another project than their (clear) building's | 40,078 (5,510 sales, 34,568 leases), shown under the wrong project | 14,196 (4,107 sales, 10,089 leases), all filed under their building's project |
| Records in another project than their building's, building clear | 40,078 | 0 |
| Records in another project than their building's, building not clear (< 80%) | not counted | 16,656 (7,627 sales, 9,029 leases), unchanged |
| Nice 1 / Nice 2 | 697 + 114 crossed / 511 + 112 crossed | 819 / 630, none crossed; 551 / 452 plots counted |
| Projects with a register count | 3,445 | 3,543 |
| Buildings with a register count | 4,075 | 4,183 |
| DXBI sales / leases paired with DLD | 964,280 / 1,418,877 | 964,401 / 1,418,882 |

Second pass, same day (user: "do all the fixes, check the web where they are the same or
different"). The 16,656 records whose building was under 80% agreement were three cases:

- **A project named like the building** is its project, whatever the share (Spring Oasis, 61%
  It Plaza pairings; Dubai Jewel Tower vs Silver Park Residency in Warsan Fourth). Web: Spring
  Oasis is a residential tower, IT Plaza an office building; Jewel Tower is in Internet City.
- **Sister phases of one master community** re-file at >= 60% (Damac Hills 2 clusters,
  International City clusters). Where a name splits below 60% between sisters it is one
  building per project: DLD's register has Capria East buildings 1-9 (plot 527) and Capria
  West buildings 1-12 (plot 528), so "Capria 5" is two buildings.
- **A project in another master community** (a price-and-date pairing across the city:
  Manchester Tower to Azizi Mirage 1) re-files at >= 50%.
- **Generic names** ("Tower A", "Building 2") take DXBI's own project as part of the building:
  DXBI files every "Tower A" sale under Club Drive, Address Residences, Golf Horizon, Damac
  Towers by Paramount, etc. "G-24" is a named building, not a generic one.
- **One development DLD registers as two projects** merge (`project_aliases.csv`, with the web
  evidence): Palm Central Private Residences (Frond M + Frond N; Nakheel: one development
  between the fronds), Bellagio by Sunrise (+ Bellavion by Sunrise; Sunrise Capital: two blocks,
  255 units).

| | After first pass | After second pass |
|---|---:|---:|
| Records re-filed to their building's project | 14,196 | 30,413 |
| Records in another project than their building's | 16,656 | 40, then 3 (see below) |
| Projects / buildings with a register count | 3,543 / 4,183 | 3,550 / 4,203 |

The 40 (listed in `remaining_40_records.csv`) were buildings of under 10 records: a small
building (3-9) now re-files at 60% unless generic (Oberoi Centre, Urbana stacked-house blocks,
Executive Towers Plaza Boutiques), and in a building of under 5 records one record named like
the building decides (Emaar Square 5, The Pulse Beachfront, Binghatti Galaxy). Three remain: two
leases of Mog 193 unit 308 (Discovery Gardens, its building 51% Mogul Cluster; the two sources
disagree) and one sale in a 2-record I Suites building. Executive Bay Podium's one Executive Bay B
lease re-filed to Executive Bay A (2 of its 3 records), but its own DLD lease (same dates and
1,268 sqft) is Executive Bay B: a podium's name now counts as generic, so its records keep their
pairing. Five remain in another project than their building's: the three above and two podium
records, by design.

Pairing and size (measured 22 Oct 2026 on the current pairs; a pair "agrees" when its project is
its clear building's, "disagrees" when it was re-filed):

| Size gap DXBI vs DLD | Sales: pairs / agree / disagree | Leases: pairs / agree / disagree |
|---|---|---|
| <= 5% | 821,200 / 797,196 / 4,560 (0.6% wrong) | 356,589 / 315,960 / 4,157 (1.3%) |
| 5-20% | 3,210 / 2,400 / 737 (24%) | 3,202 / 593 / 1,368 (70%) |
| 20-50% | 2,015 / 1,062 / 854 (45%) | 2,934 / 470 / 1,211 (72%) |
| > 50% | 1,791 / 727 / 868 (54%) | 2,152 / 270 / 910 (77%) |
| a side has no size | 12,426 / 12,221 / 132 | 412 / 45 / 154 |

A size check (both sizes known) is worth it for leases at 5%: it would drop 8,288 pairs, about
3,500 of them wrong and 1,300 right. For sales it is a coin flip beyond 20% (about half of those
pairs agree with their building) and is not proposed. Applied for leases on 22 Oct (user):
leases paired 1,418,882 -> 1,411,948; leases re-filed because their pairing named another
project 22,1xx -> 17,236.

DLD's project register (`dld_od_projects_bronze`: `cnt_unit` + `cnt_villa`, newest snapshot,
September 2026) is a unit source after the unit register and before land plots, by name or by
the DLD project a unit-number link found. It counts 188 projects that showed "at least N
traded", 43 of them launched after the unit register's May snapshot. Projects with a register
count: 3,550 -> 3,730 of 4,394.

No "at least N units traded" (user, 22 Oct): a project or building shows DXBI's building-list
count, else a DLD register count, else no unit count. Its units traded stay in the stock table
(`units_traded`) as evidence but are not shown as units. 664 projects and 2,016 buildings show
no unit count; DXBI's own count covers 1,580 projects and 1,567 buildings, DLD's registers the
rest of the 3,730 / 4,199.

The building steps are now computed once into work tables (`analytics_first_ids__work`,
`analytics_record_ids__work`, `analytics_dld_votes__work`, `analytics_building_merge__work`);
inlined as CTEs they recomputed the chain several times, outgrew 9 GB and took 8-12 minutes.
The hierarchy build now takes 89 seconds.

Re-filed records: `~/vv/analytics-hierarchy-audit-2026-10-21/refiled_by_building.csv`.

### 5. Not changed (waiting for review)

- The wrong-project records (decision 3).
- Pairing rules in `transforms.py` (fixes are proposed in the error analysis).

## Order

1. Curated CSVs: master aliases, project masters, project aliases (with evidence).
2. Holocron module, schema, tests; build on the local warehouse (one heavy build at a time).
3. Backend: dxbi.py, queries, service, router, models, tests.
4. Frontend: selector, panel, compare; tests.
5. Verify: re-run the audit (exact duplicates 0; projects under one master; unit coverage),
   check Skyrise, Merano and two villa communities against DXBI, run all suites, browser pass.

## Results (local warehouse, 21 Oct 2026)

| Check | Before | After |
|---|---:|---|
| Project names that differ only in case or punctuation | 174 groups | 0 |
| Master names (spellings, sub-communities, projects as masters) | 469 | 177 |
| Projects under more than one master | 1,307 | 0 |
| Projects with a register unit count | 1,918 (41%) | 3,311 of 4,506 (73%) on the first pass; **3,445 (76%)** after section 6; 942 more show "at least N units traded" |
| Buildings with a unit count | 0 (no view) | 3,863 of 6,536 (59%) on the first pass; **4,075 of 6,223 (65%)** after section 6 (280 duplicate buildings merged); 2,124 more "at least N traded" |
| Masters with a unit count | 0 | every master: its projects' register counts added up, with "N of M projects counted" |
| Building selection | opened the project | its own scope on every endpoint (`filter_type=building`, `building_id`) |
| Records filed under another project than their building's | 38,679 (audit) | 39,975 marked `stray = 1`, listed for review; 40,078 after the building merges (159 added, 56 cleared: `wrong_project_records_delta.csv`) |

Notes:

- DLD's project register `no_of_units` agrees with its unit register for 2,121 of 2,563 projects
  matched by project id (39 doubled). The audit's "about double" came from matching by name; Upcoming
  Supply is unchanged.
- Traded units count only a project's own buildings (and, for a project without buildings, its
  records), and a unit share ("2510 (Q 3)", Ciel) is its unit: building-less leases that pairing
  attached to a project are often another building's units.

Section 6, step by step (projects / buildings with a register count; gaps P1–P4, B1–B3 as in
`unit_count_gaps.md`):

| Step | Projects | Buildings | Gaps after |
|---|---:|---:|---|
| First pass | 3,311 | 3,863 of 6,536 | P1 237, P2 41, P3 196, P4 53; B1 781, B2 836, B3 36 |
| Link projects by unit numbers (423 links) | 3,434 | 4,077 | P1 125; B2 595 |
| Floor-area tie-break; twin-tower ties link nothing; shared DLD buildings count for neither | 3,426 | 4,165 of 6,507 | B1 610; 8 projects lose a doubled sum |
| Unit key, non-residential codes, plots, same-name buildings merged | 3,445 | 4,075 of 6,223 | P1 127, P2 44, P3 174, P4 53; B1 591, B2 575, B3 26 |

What is left, and why it is not counted (listed with evidence in `unit_count_gaps.md`):

- P1 127: unit numbers split over several DLD buildings or projects (65), not in the register at
  their floor areas (32), the DLD project another DXBI project holds by name (11, likely a phase
  or a duplicate), fewer than 5 matches (9), twin buildings (7), claimed by two projects (3).
- P2 44 and B3 26: the register holds fewer units than traded even with one unit key: upper
  floors or towers missing from the register (Skyvue D76xx, New Dubai Gate 1 B-7xx), villa codes
  under a commercial register entry (Jumeirah Park), DXBI numbering DLD does not use (101A/101B).
- P3 174: off-plan villa phases whose sub-plots DLD has not registered, and apartment projects
  whose land register entry is the one site plot.
- P4 53: first record after the May 2026 unit snapshot; DLD's units endpoint returns no rows.
- Not countable from current data: villa clusters without a plot list, DXBI-only buildings, fewer
  than 3 unit numbers, no unit numbers.

Checks run: holocron 611 passed (live ClickHouse) with `ty` and ruff; backend unit/contract 223
and ClickHouse 78; frontend vitest 71 and svelte-check; Playwright Analytics specs 24 (new
`e2e/analytics-hierarchy.spec.ts`, screenshots in `docs/audits/analytics-hierarchy-2026-10-21/`).

Checks run after section 6: holocron 613 passed (live ClickHouse; new tests: a project DLD files
under no name gets its register count, repeated unit numbers resolve by floor area, format
variants and a parking code do not inflate traded units, one name across communities is one
building, a DLD building two buildings match counts for neither), `ty` and ruff; backend
ClickHouse 78 and unit/contract 223; frontend vitest 71 and svelte-check; Playwright Analytics
specs 24.
