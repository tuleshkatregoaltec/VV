# Scraping dubailand.gov.ae — Research Notes

## Background

The original DLD scraper fetched full historical CSV dumps from `dubaipulse.gov.ae`.
That site now redirects to `data.dubai`, which is WAF-blocked for all server-side requests
(returns "Request Rejected" for any non-browser User-Agent or IP).

The replacement source is the dubailand.gov.ae gateway API.

---

## Gateway API

Base URL: `https://gateway.dubailand.gov.ae/open-data`

### Authentication / headers

Every request must include:

```
consumer-id: gkb3WvEG0rY9eilwXC0P2pTz8UzvLj9F
AppUser: (empty string)
Accept: application/json, */*
Content-Type: application/json; charset=utf-8
Origin: https://dubailand.gov.ae
Referer: https://dubailand.gov.ae/en/open-data/real-estate-data
User-Agent: Mozilla/5.0 ...
```

The `consumer-id` is a public static key embedded in `window.apiConfig.consumerId` on the
dubailand.gov.ae open-data page. As of 2026-03-14 it is still `gkb3WvEG0rY9eilwXC0P2pTz8UzvLj9F`.
To check if it has changed: `curl -s https://dubailand.gov.ae/en/open-data/real-estate-data | grep -o '"consumerId":"[^"]*"'`

### HTTP method and body

**All requests are POST with a JSON body** — GET returns `{"message": "no Route matched with those values"}`.

Date format in the JSON body is **MM/DD/YYYY** (American), NOT DD/MM/YYYY.
The JS on the website converts the UI date (DD/MM/YYYY) to MM/DD/YYYY before calling the API:
`moment(value, 'DD/MM/YYYY').locale('en').format("MM/DD/YYYY")`

**`P_SORT` is required** for at least `transactions` — omitting it returns 500.

### Response envelope

```json
{
  "timeStamp": "...",
  "responseCode": 200,
  "validationErrorsList": [],
  "response": {
    "result": [ { "RN": 1, "TOTAL": 52318, ... }, ... ],
    "additionalData": null
  }
}
```

`result[0].TOTAL` is the total record count across all pages (every row carries it).

---

## Endpoint status (as of 2026-03-14)

| Endpoint | HTTP | Records | Notes |
|---|---|---|---|
| `transactions` | 200 ✅ | 52,318 | YTD 2026 only |
| `rents` | 200 ✅ | 244,637 | YTD 2026 only; needs `P_DATE_TYPE: ""` |
| `buildings` | 200 ⚠️ | 3,180 | All-time, but very limited vs full registry |
| `units` | 200 ⚠️ | 0 | Returns 200 but empty result array |
| `projects` | 200 ⚠️ | 0 | Returns 200 but empty |
| `developers` | 200 ⚠️ | 0 | Returns 200 but empty |
| `lands` | 500 ❌ | — | Application error |
| `valuations` | 500 ❌ | — | Application error |
| `*/export/csv` | 500 ❌ | — | Blocked for all endpoints |

---

## YTD-only limitation

**Confirmed**: the API only serves current-year (2026) data regardless of the date range supplied.
Years 2015, 2020, 2023, 2024 all return empty results for transactions.
The website's date picker also enforces this (`minDate: new Date(year, 0, 1)`).

This means the gateway API **cannot replace Dubai Pulse** as a source for historical data.
It can only be used for incremental current-year updates.

---

## Working request examples

### transactions
```bash
curl -s --compressed -X POST "https://gateway.dubailand.gov.ae/open-data/transactions" \
  -H "consumer-id: gkb3WvEG0rY9eilwXC0P2pTz8UzvLj9F" \
  -H "AppUser: " \
  -H "Accept: application/json, */*" \
  -H "Origin: https://dubailand.gov.ae" \
  -H "Referer: https://dubailand.gov.ae/en/open-data/real-estate-data" \
  -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "P_FROM_DATE": "01/01/2026",
    "P_TO_DATE":   "03/14/2026",
    "P_GROUP_ID": "", "P_IS_OFFPLAN": "", "P_IS_FREE_HOLD": "",
    "P_AREA_ID": "", "P_USAGE_ID": "", "P_PROP_TYPE_ID": "",
    "P_TAKE": "500", "P_SKIP": "0",
    "P_SORT": "INSTANCE_DATE DESC"
  }'
```

### rents (note: `P_DATE_TYPE` must be `""`, not `"CONT"`)
```bash
curl -s --compressed -X POST "https://gateway.dubailand.gov.ae/open-data/rents" \
  -H "consumer-id: gkb3WvEG0rY9eilwXC0P2pTz8UzvLj9F" \
  -H "AppUser: " \
  -H "Accept: application/json, */*" \
  -H "Origin: https://dubailand.gov.ae" \
  -H "Referer: https://dubailand.gov.ae/en/open-data/real-estate-data" \
  -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "P_FROM_DATE": "01/01/2026",
    "P_TO_DATE":   "03/14/2026",
    "P_DATE_TYPE": "", "P_IS_FREE_HOLD": "", "P_VERSION": "",
    "P_AREA_ID": "", "P_USAGE_ID": "", "P_PROP_TYPE_ID": "",
    "P_TAKE": "500", "P_SKIP": "0",
    "P_SORT": "CONTRACT_START_DATE DESC"
  }'
```

### buildings (no date filter — returns all-time ~3K records)
```bash
curl -s --compressed -X POST "https://gateway.dubailand.gov.ae/open-data/buildings" \
  -H "consumer-id: gkb3WvEG0rY9eilwXC0P2pTz8UzvLj9F" \
  -H "AppUser: " \
  -H "Accept: application/json, */*" \
  -H "Origin: https://dubailand.gov.ae" \
  -H "Referer: https://dubailand.gov.ae/en/open-data/real-estate-data" \
  -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "P_FROM_DATE": "", "P_TO_DATE": "",
    "P_IS_FREE_HOLD": "", "P_AREA_ID": "", "P_ZONE_ID": "",
    "P_IS_LEASE_HOLD": "", "P_IS_OFFPLAN": "",
    "P_TAKE": "500", "P_SKIP": "0",
    "P_SORT": "PROPERTY_ID ASC"
  }'
```

---

## API parameters per endpoint

From `https://dubailand.gov.ae/scripts/publicData.js`:

| Endpoint | Parameters |
|---|---|
| transactions | `P_FROM_DATE, P_TO_DATE, P_GROUP_ID, P_IS_OFFPLAN, P_IS_FREE_HOLD, P_AREA_ID, P_USAGE_ID, P_PROP_TYPE_ID, P_TAKE, P_SKIP, P_SORT` |
| rents | `P_FROM_DATE, P_TO_DATE, P_DATE_TYPE, P_IS_FREE_HOLD, P_VERSION, P_AREA_ID, P_USAGE_ID, P_PROP_TYPE_ID, P_TAKE, P_SKIP, P_SORT` |
| buildings | `P_FROM_DATE, P_TO_DATE, P_IS_FREE_HOLD, P_AREA_ID, P_ZONE_ID, P_IS_LEASE_HOLD, P_IS_OFFPLAN, P_TAKE, P_SKIP, P_SORT` |
| units | `P_AREA_ID, P_ZONE_ID, P_IS_FREE_HOLD, P_IS_LEASE_HOLD, P_IS_OFFPLAN, P_TAKE, P_SKIP, P_SORT` |
| projects | `P_FROM_DATE, P_TO_DATE, P_DATE_TYPE, P_PRJ_TYPE_ID, P_PRJ_STATUS, P_ZONE_ID, P_AREA_ID, P_TAKE, P_SKIP, P_SORT` |
| developers | `P_FROM_DATE, P_TO_DATE, P_NAME, P_TAKE, P_SKIP, P_SORT` |
| valuations | `P_FROM_DATE, P_TO_DATE, P_AREA_ID, P_PROP_TYPE_ID, P_TAKE, P_SKIP, P_SORT` |

---

## API response field names vs ClickHouse schema

### transactions → ch_transactions

| API field | CH column |
|---|---|
| `TRANSACTION_NUMBER` | `transaction_id` |
| `PROCEDURE_ID` | `procedure_id` |
| `GROUP_ID` | `trans_group_id` |
| `GROUP_AR` | `trans_group_ar` |
| `GROUP_EN` | `trans_group_en` |
| `PROCEDURE_AR` | `procedure_name_ar` |
| `PROCEDURE_EN` | `procedure_name_en` |
| `INSTANCE_DATE` | `instance_date` |
| `PROPERTY_TYPE_ID` | `property_typeB_id` |
| `PROP_TYPE_AR` | `property_type_ar` |
| `PROP_TYPE_EN` | `property_type_en` |
| `PROP_SUB_TYPE_ID` | `property_sub_type_id` |
| `PROP_SB_TYPE_AR` | `property_sub_type_ar` |
| `PROP_SB_TYPE_EN` | `property_sub_type_en` |
| `USAGE_AR` | `property_usage_ar` |
| `USAGE_EN` | `property_usage_en` |
| `IS_OFFPLAN` | `reg_type_id` *(maps differently — check)* |
| `AREA_ID` | `area_id` |
| `AREA_AR` | `area_name_ar` |
| `AREA_EN` | `area_name_en` |
| `PROJECT_AR` | `project_name_ar` |
| `PROJECT_EN` | `project_name_en` |
| `MASTER_PROJECT_EN` | `master_project_en` |
| `MASTER_PROJECT_AR` | `master_project_ar` |
| `NEAREST_LANDMARK_AR` | `nearest_landmark_ar` |
| `NEAREST_LANDMARK_EN` | `nearest_landmark_en` |
| `NEAREST_METRO_AR` | `nearest_metro_ar` |
| `NEAREST_METRO_EN` | `nearest_metro_en` |
| `NEAREST_MALL_AR` | `nearest_mall_ar` |
| `NEAREST_MALL_EN` | `nearest_mall_en` |
| `ROOMS_EN` | `rooms_en` |
| `ROOMS_AR` | `rooms_ar` |
| `PROCEDURE_AREA` | `procedure_area` |
| `TRANS_VALUE` | `actual_worth` |
| `IS_FREE_HOLD` | `reg_type_id` *(also maps here — needs clarification)* |

**Note:** The gateway API response does NOT include `transaction_id`, `meter_sale_price`,
`meter_rent_price`, `rent_value`, `has_parking`, `no_of_parties_role_*`, `project_number`,
`building_name_*`. These are present in the old Dubai Pulse CSV but missing from the gateway.
The schema may need adjustment or these fields left NULL for gateway-sourced rows.

### rents → ch_rent_contracts
Key fields present: `CONTRACT_NUMBER`, `REGISTRATION_DATE`, `START_DATE`, `END_DATE`,
`CONTRACT_AMOUNT`, `ANNUAL_AMOUNT`, `AREA_ID`, `AREA_EN/AR`, `ACTUAL_AREA`,
`EJARI_PROPERTY_TYPE_ID`, `PROP_TYPE_EN/AR`, `EJARI_PROPERTY_SUB_TYPE_ID`,
`PROP_SUB_TYPE_EN/AR`, `USAGE_EN/AR`, `PROJECT_EN/AR`, `MASTER_PROJECT_EN/AR`,
`IS_FREE_HOLD`, `VERSION_NUMBER`, `PROPERTY_ID`, `PARCEL_ID`, `NEAREST_*`.

The API does NOT include: `contract_reg_type_id/en/ar`, `no_of_prop`, `line_number`,
`ejari_bus_property_type_*`, `tenant_type_*`.

---

## Architecture implications

### Full-refresh pattern is broken
The current `ClickHouseResource.load_table_from_s3()` does EXCHANGE TABLES (full-replacement).
This cannot be used with YTD-only data — it would wipe all historical rows every run.

### Required change for transactions/rents
Switch to **incremental INSERT + deduplication**:
- Use `ReplacingMergeTree` and insert new rows — ClickHouse deduplicates by ORDER BY key
- Or: use `INSERT INTO ... SELECT ... WHERE id NOT IN (SELECT id FROM target)` pattern
- Or: accept duplicates and use `FINAL` keyword in reads

### Reference tables (buildings, units, projects, developers)
These are dimension tables that change slowly. Since the gateway returns limited or empty data
for these, they should be treated as static until a better source is found. Do not overwrite
with the 3,180-row gateway response if you have the full historical data.

---

## CaptchaProxy (not yet useful)

The website routes through `/umbraco/surface/CaptchaProxy/CallThenPost` when
`AppInfo.featureGate.captchaEnabled = true` (which it is). The proxy validates a
reCAPTCHA v3 token (site key: `6LfLwbUrAAAAAGxG1Jx890EGQs5QS9cNYTdSpur-`) before
forwarding to the gateway. The endpoint accepts requests and returns `"Invalid Captcha"` for
fake tokens, so it IS reachable.

A Playwright-based approach could obtain a valid v3 token without user interaction, but:
1. It still only returns YTD data
2. The CSV export endpoint also returns 500 even server-side
So captcha bypass is low priority until the YTD limitation is resolved.

---

## Next steps / open questions

1. **Implement the gateway scraper** for transactions + rents as an incremental append pipeline.
   Pagination: use `P_TAKE` (max tested: 500) + `P_SKIP`. Sort by `INSTANCE_DATE ASC` for
   stable pagination. Stop when `len(result) < P_TAKE`.

2. **Decide on dedup strategy** for ClickHouse: ReplacingMergeTree vs INSERT ... WHERE NOT EXISTS.

3. **Investigate if units/projects/developers work with different parameters** — they return
   empty but 200, which might mean the sort field or a required filter is wrong.

4. **Find a source for historical data** (pre-2026):
   - Try a Playwright session on dubailand.gov.ae to see if clicking the export button
     downloads a file with historical data
   - Check if data.dubai has a machine-readable API on a different subdomain/path
   - Consider that the existing data in ClickHouse may already be the historical baseline
     and the pipeline only needs to append going forward
