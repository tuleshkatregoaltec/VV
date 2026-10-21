# Analytics hierarchy: implementation plan

Status: implemented on the local warehouse, 21 Oct 2026 (branch `feat/dxbi-dld-complete-match`, #46).
The one open item is the review of the wrong-project records (decision 3).
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
| Projects with a register unit count | 1,918 (41%) | 3,311 of 4,506 (73%); 1,074 more show "at least N units traded" |
| Buildings with a unit count | 0 (no view) | 3,863 of 6,536 with a register count; 2,662 more "at least N traded" |
| Masters with a unit count | 0 | every master: its projects' register counts added up, with "N of M projects counted" |
| Building selection | opened the project | its own scope on every endpoint (`filter_type=building`, `building_id`) |
| Records filed under another project than their building's | 38,679 (audit) | 39,975 marked `stray = 1`, unchanged, listed for review |

Notes:

- DLD's project register `no_of_units` agrees with its unit register for 2,121 of 2,563 projects
  matched by project id (39 doubled). The audit's "about double" came from matching by name; Upcoming
  Supply is unchanged.
- Traded units count only a project's own buildings (and, for a project without buildings, its
  records), and a unit share ("2510 (Q 3)", Ciel) is its unit: building-less leases that pairing
  attached to a project are often another building's units.

Checks run: holocron 611 passed (live ClickHouse) with `ty` and ruff; backend unit/contract 223
and ClickHouse 78; frontend vitest 71 and svelte-check; Playwright Analytics specs 24 (new
`e2e/analytics-hierarchy.spec.ts`, screenshots in `docs/audits/analytics-hierarchy-2026-10-21/`).
