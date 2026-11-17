# CRM rental ranked base

`crm_rental_ranked_base` is a manual downstream Holocron asset. It publishes the existing
rental identity ranking once; date windows, lease evidence, scores and coverage remain live.
`CRM_RENTAL_BASE_ENABLED` defaults to `false`. Registering the asset enables no schedules,
source ingestion jobs or publication against an existing warehouse.

## Canonical contract

The pure `crm-rental-sql` package under `holocron/packages/crm-rental-sql` owns the SQL shared
by the backend and Holocron. Both locked environments install that package; the backend image
copies it explicitly. It imports no FastAPI application or settings. The extracted live and
area CTEs are byte-identical to the previous application SQL; `FINAL`, tie ordering and scoring
are preserved. Saved leads and lead detail retain the live relation, including `identified_unit`
and legacy-table fallback. Saved joined columns have their ClickHouse `l.` qualifier removed
before the existing lead projection.

The canonical `PUBLICATION_POLICY` is `crm-rental-ranked-base/v2-exact-display-area`.
Both publisher and runtime require that marker kind. The transform revision includes the
policy and its validation SQL, so older unchecked artifacts cannot serve after this upgrade.

The revision includes the canonical transform hash and metadata for all dependencies:

- Physical tables: `dxbi_rental_events`, `dxbi_rental_unit_candidates`,
  `dxbi_rental_sale_matches`, `geo_source_signatures`, `geo_entity_links`,
  `geo_location_nodes`, `geo_location_closure`.
- Views: `geo_mapped_source_facts`, `geo_crm_rental_hierarchy`.

Table UUIDs, DDL and active part identities/checksums participate. Pending mutations prevent
publication/use. Changes to matches, events, geography or views invalidate the base even if
candidate `loaded_at` is unchanged. Background merges conservatively invalidate it too.
Readiness checks read `system.tables`, `system.columns`, `system.parts` and `system.mutations`;
they do not scan source data. A disabled flag performs no readiness queries.

## Publication and fallback

Only an ingestion writer may materialize the asset. It acquires the atomic DDL name
`crm_rental_ranked_base_publish_guard`, validates the complete pre-ranking `identified_unit`
relation, and builds a unique private staging table with the exact canonical ranking. It
checks nonempty/unique ranked identities and rechecks the dependency revision. Validation and
build share that before/after fingerprint window.

Publication refuses any property identity spanning distinct **exact display area** labels:
`GROUP BY property_identity_key HAVING min(area_name) != max(area_name)`. The unchanged identity
normalization folds labels such as `Test-Area` and `Test Area` together; global ranking could
otherwise hide the older lease selected by the live area's earlier source pruning. Checking
only rank-one rows would miss this collision. Rejection preserves the previous artifact and
its marker; changed-source freshness forces live fallback, preserving the area's older lease.
Different registry aliases that map to the same exact display area remain publishable.
Build statements are bounded to two threads, 3 GB and 60 seconds. A JSON table `COMMENT`
contains the validated source revision, transform hash, schema hash and row count. The marker
is written only on the completed private staging table. `EXCHANGE TABLES` publishes rows and
the marker together; first publication uses atomic `RENAME TABLE`. The previous artifact and
its marker remain in `crm_rental_ranked_base_previous` after a successful replacement.

The runtime checks the current publication policy, schema, engine, nonempty row count and dependency revision
before choosing the base. Missing, old, empty, stale or incompatible artifacts and metadata
errors use the canonical live query. Selected display areas use `PREWHERE area_name IN ...`
on the leading sorting key before reading the full row payload. Registry names remain in the
rows, and the shared live area query still prunes registry aliases before joining/ranking.

## Rollout and recovery

1. Deploy compatible backend/Holocron packages with the flag disabled. Grant the runtime
   read-only access to the serving base and required system metadata; retain its live-source
   permissions for fallback.
2. Confirm the relevant upstream dataset publications have completed. Keep upstream writers
   quiescent during manual materialization. Per-dataset release manifests do **not** establish
   an atomic global release: before/after metadata checks prove observed stability, not a
   transactional snapshot across all inputs. This asset creates no global publication system.
3. Materialize only this downstream asset with the ingestion writer. Inspect its Dagster
   metadata and serving-table comment, then validate staging outputs and representative load
   before enabling the runtime flag. A different deployed transform hash falls back live.
4. Disable the flag to revert serving behavior immediately. Keep the previous artifact for
   inspection; exchange it back only if its source revision is still valid, otherwise rebuild.

A crashed publisher deliberately leaves its DDL guard in place, so another run cannot overlap
an unknown active build. An operator must first confirm the interrupted Dagster run and its
ClickHouse statements have stopped. Only then remove `crm_rental_ranked_base_publish_guard`
and inspect/remove abandoned `crm_rental_ranked_base_staging_*` tables before retrying. Never
remove an active run's guard or staging table. An exchange followed by cleanup failure can
leave the old artifact under its unique staging name; inspect table markers before cleanup.
No operational warehouse build, grant change, deployment or flag enablement was performed
as part of this implementation.

## Verification

The disposable ClickHouse acceptance suite compares all columns across 75 named
as-of/lookback/area combinations, actual dashboard/renewal/agent/area outputs and projections,
including nonfinite values. It verifies saved aliases, failed-build retention, stale-source
fallback, the previous artifact's marker, and the exact-area collision counterexample with
unchanged prior rows/checksum/marker and the older selected lease returned through live fallback. An unrelated-area fixture measured 8,192 rows
read with area pruning versus 25,041 for the full base. This is a regression fixture, not a
production capacity benchmark. All fixture databases are created uniquely and dropped.

Run `just test-backend-clickhouse -k crm_rental_base -rP` for that acceptance check.
`just holocron check` covers asset registration, publication failure paths and the full
Holocron static/unit checks. Existing optional live Holocron checks remain skipped without
their explicit external-service configuration; production concurrency/cutover acceptance
remains a rollout requirement.
