-- Basic sanity checks — run after each load.

-- Row counts
SELECT 'ch_transactions'   AS tbl, count() AS rows FROM ch_transactions;
SELECT 'ch_rent_contracts' AS tbl, count() AS rows FROM ch_rent_contracts;
SELECT 'ch_projects'       AS tbl, count() AS rows FROM ch_projects;
SELECT 'ch_buildings'      AS tbl, count() AS rows FROM ch_buildings;
SELECT 'ch_units'          AS tbl, count() AS rows FROM ch_units;
SELECT 'ch_land_registry'  AS tbl, count() AS rows FROM ch_land_registry;
SELECT 'ch_developers'     AS tbl, count() AS rows FROM ch_developers;
SELECT 'ch_gis_land_plots' AS tbl, count() AS rows FROM ch_gis_land_plots;
SELECT 'ch_geo_buildings'  AS tbl, count() AS rows FROM ch_geo_buildings;
SELECT 'ch_geo_projects'   AS tbl, count() AS rows FROM ch_geo_projects;

-- Null primary keys (should return 0)
SELECT count() AS empty_transaction_ids FROM ch_transactions   WHERE transaction_id = '';
SELECT count() AS zero_project_ids      FROM ch_projects       WHERE project_id = 0;
SELECT count() AS zero_property_ids     FROM ch_buildings       WHERE property_id = 0;
SELECT count() AS zero_property_ids     FROM ch_units           WHERE property_id = 0;

-- Geo bounds — Dubai bounding box
SELECT count() AS out_of_bounds FROM ch_geo_buildings
WHERE lat NOT BETWEEN 24.7 AND 25.4 OR lng NOT BETWEEN 54.8 AND 55.6;
