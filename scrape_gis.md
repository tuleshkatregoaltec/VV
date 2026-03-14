# DDA GIS Scraping

Source: https://gis.dda.gov.ae/DIS

## Authentication

All ArcGIS REST queries require a token. The token is a short-lived, read-only session
token (`AGSToken`) embedded in the DIS page HTML as a JS variable:

```
"AGSToken": "abc123..."
```

Extract with: `"AGSToken"\s*:\s*"([^"]+)"`

The portal token endpoint (`/portal/sharing/rest/generateToken`) requires credentials and
cannot generate an anonymous token. Fetching the DIS page as an anonymous user is
sufficient — the server embeds the token for the public web app.

## MapServer

```
https://gis.dda.gov.ae/server/rest/services/DIS/MAIN_MAP/MapServer
```

Relevant layers:

| ID | Name                  | Geometry  | Notes                          |
|----|-----------------------|-----------|--------------------------------|
| 10 | Project Limit Outline | Polygon   | 208 project polygons           |
| 12 | Project Limit         | Polygon   | (alternate, not used)          |
| 13 | Plot                  | Polygon   | ~all land plots; paginated     |

## Layer 13 — Plot

Used for: `raw_gis_plots` → `ch_gis_land_plots`

Fields from the ArcGIS query (layer attributes):
- `PLOT_NUMBER`, `OLD_PLOT_NUMBERS`, `LANDUSE_SYMBOLS`, `GFA_TYPE`, `IS_VERIFIED`, `VERIFY_COMMENTS`

Full plot details (project name, area, GFA, setbacks, land use, coordinates) are fetched
per-plot via a separate handler:

```
GET /DIS?handler=PlotInfo&plotNumber={PLOT_NUMBER}
```

Returns HTML. Parsed with regex into the fields in `CSV_FIELDS` (see `dda_gis.py`).

Pagination: 2000 records per page. Total plots is in the tens of thousands.
The `coordinates` field contains the plot polygon rings in JSON as `[[easting, northing], ...]`
in the native projected CRS (WKID 3997, Dubai local).

## Layer 10 — Project Limit Outline

Used for: `raw_project_polygons` → `ch_geo_projects`

Fields: `OBJECTID` (Int32), `ProjectName` (String 255)

- **208 total records** — fits in a single request (no pagination needed)
- Request `outSR=4326` to receive polygon rings in WGS84 lon/lat
- Geometry type: `esriGeometryPolygon` (multi-ring polygons)
- Spatial reference (native): WKID 3997 (projected, metres, Dubai area)

Example projects: AL WAHA, JADDAF WATERFRONT, DUBAI HEALTHCARE CITY PHASE 2,
JUMEIRAH BEACH RESIDENCE, DUBAI CREEK HARBOUR, DUBAI HILLS, DAMAC HILLS,
BLUEWATERS, BUSINESS BAY, ARJAN.

Note: "DUBAI MARINA" is absent from this layer. JBR is the closest waterfront project.

Query used:

```
GET /server/rest/services/DIS/MAIN_MAP/MapServer/10/query
  ?where=1=1
  &outFields=OBJECTID,ProjectName
  &returnGeometry=true
  &outSR=4326
  &resultRecordCount=2000
  &f=json
  &token={AGSToken}
```

## CSV Schemas

### dda_plots.csv (layer 13 + PlotInfo handler)

| Column               | Type   | Notes                                   |
|----------------------|--------|-----------------------------------------|
| plot_number          | string | primary key                             |
| old_numbers          | string |                                         |
| project_name         | string |                                         |
| community_name       | string |                                         |
| master_developer     | string |                                         |
| plot_area_sqm        | float  |                                         |
| plot_area_sqft       | float  |                                         |
| max_gfa_sqm          | float  |                                         |
| max_gfa_sqft         | float  |                                         |
| max_height           | string |                                         |
| max_coverage         | string |                                         |
| site_plan_issue_date | string |                                         |
| site_plan_expiry_date| string |                                         |
| side1_building       | string | setback (sides 1–4)                     |
| side1_podium         | string |                                         |
| ... (sides 2–4)      |        |                                         |
| land_use             | json   | `[{"type": ..., "use": ...}, ...]`      |
| general_notes        | string | pipe-delimited list items               |
| coordinates          | json   | `[[easting, northing], ...]` WKID 3997  |
| landuse_symbols      | string |                                         |
| gfa_type             | string |                                         |
| is_verified          | string |                                         |
| verify_comments      | string |                                         |

### project_polygons.csv (layer 10)

| Column       | Type   | Notes                                              |
|--------------|--------|----------------------------------------------------|
| object_id    | int    | ArcGIS OBJECTID                                    |
| project_name | string | e.g. "JUMEIRAH BEACH RESIDENCE"                    |
| rings        | json   | `[[[lng, lat], ...], ...]` WGS84, outer ring first |

## Scraper Code

| File                              | Purpose                                      |
|-----------------------------------|----------------------------------------------|
| `etl/lib/scrapers/dda_gis.py`     | `scrape()` for plots, `scrape_projects()` for project polygons |
| `etl/assets/gis.py`               | `raw_gis_plots` Dagster asset                |
| `etl/assets/geo.py`               | `raw_project_polygons` Dagster asset         |

## Operational Notes

- The `AGSToken` is short-lived. It is fetched fresh at the start of each scrape run.
- The plot scraper supports resume: if the output CSV already exists with partial data,
  it skips already-fetched plot numbers.
- Concurrency for plot info fetches is configurable (default 15). The WAF will block if
  too aggressive — the scraper detects this via the absence of `form-info-dda` in the response.
- The project polygon scrape is a single request and completes in under a second.
