-- Basic sanity checks — run after each load.

-- Row counts
SELECT 'dld_transactions'        AS tbl, count() AS rows FROM dld_transactions;
SELECT 'dld_rent_contracts'      AS tbl, count() AS rows FROM dld_rent_contracts;
SELECT 'dld_projects'            AS tbl, count() AS rows FROM dld_projects;
SELECT 'dld_buildings'           AS tbl, count() AS rows FROM dld_buildings;
SELECT 'dld_units'               AS tbl, count() AS rows FROM dld_units;
SELECT 'dld_land_registry'       AS tbl, count() AS rows FROM dld_land_registry;
SELECT 'dld_developers'          AS tbl, count() AS rows FROM dld_developers;
SELECT 'gis_land_plots'          AS tbl, count() AS rows FROM gis_land_plots;
SELECT 'gis_project_areas'       AS tbl, count() AS rows FROM gis_project_areas;
SELECT 'gis_subproject_areas'    AS tbl, count() AS rows FROM gis_subproject_areas;
SELECT 'gis_plot_building_limits' AS tbl, count() AS rows FROM gis_plot_building_limits;
SELECT 'gis_plot_podium_limits'  AS tbl, count() AS rows FROM gis_plot_podium_limits;
SELECT 'gis_plot_features'       AS tbl, count() AS rows FROM gis_plot_features;
SELECT 'gis_frozen_plots'        AS tbl, count() AS rows FROM gis_frozen_plots;
SELECT 'gis_landuse_symbols'     AS tbl, count() AS rows FROM gis_landuse_symbols;
SELECT 'gis_plot_built_to_lines' AS tbl, count() AS rows FROM gis_plot_built_to_lines;
SELECT 'gis_plot_arcades'        AS tbl, count() AS rows FROM gis_plot_arcades;
SELECT 'gis_plot_retail'         AS tbl, count() AS rows FROM gis_plot_retail;
SELECT 'geo_buildings'           AS tbl, count() AS rows FROM geo_buildings;

-- Null primary keys (should return 0)
SELECT count() AS empty_transaction_ids FROM dld_transactions WHERE transaction_id = '';
SELECT count() AS zero_project_ids FROM dld_projects WHERE project_id = 0;
SELECT count() AS zero_property_ids FROM dld_buildings WHERE property_id = 0;
SELECT count() AS zero_property_ids FROM dld_units WHERE property_id = 0;

-- Geo bounds — Dubai bounding box
SELECT count() AS out_of_bounds FROM geo_buildings
WHERE lat NOT BETWEEN 24.7 AND 25.4 OR lng NOT BETWEEN 54.8 AND 55.6;
