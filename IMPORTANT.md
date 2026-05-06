# Important Follow-Ups

## News images demo shortcut

For the May 2026 demo, news thumbnails are being served through a local backend disk cache instead of a proper media pipeline.

Current shortcut:
- Imported news rows store R2 object keys in `news_articles.thumbnail_url`.
- The API exposes `/api/v1/news/articles/{article_id}/thumbnail` and downloads the R2 object only if the local cache misses.
- Optimized card-size WebP files are written under `backend/.cache/news-thumbnails/`.
- This is intentionally unauthenticated because browser `<img>` requests do not include the app bearer token.
- This does not write optimized images back to R2.

After the demo:
- Move thumbnail processing into the real ingestion/media repo.
- Store durable public or signed image URLs, or serve media through a production-grade image service.
- Remove the local cache/proxy behavior if it is no longer needed.
- Revisit auth, cache headers, CDN behavior, image sizes, and fallback handling.
- Delete this note once the proper media path is in place.

## Supply catalogue demo shortcut

For the May 2026 demo, the upcoming supply catalogue is populated from the vendor export in R2 using a one-time local import.

Current shortcut:
- Run `cd backend && uv run python -m scripts.supply.import_supply_catalogue_demo` to recreate the demo data.
- The script creates local Postgres tables `demo_supply_catalogue_projects` and `demo_supply_catalogue_assets`.
- The API exposes `/api/v1/supply/catalogue/projects`, `/api/v1/supply/catalogue/projects/{project_id}`, and `/api/v1/supply/catalogue/assets/{asset_id}`.
- Images and downloadable documents are fetched from R2 on cache miss and written under `backend/.cache/supply-catalogue/assets/`.
- The asset endpoint is intentionally unauthenticated for the demo so browser image tags and brochure links work.
- This is intentionally not modeled as a durable ingestion pipeline or migration-backed production feature.

After the demo:
- Move the import into the proper data ingestion repo and promote the schema to reviewed migrations or a warehouse-backed service.
- Replace local disk asset caching with the production media pipeline, CDN/signed URLs, explicit cache headers, and image transformations.
- Decide which availability fields are trustworthy; the current catalogue uses price/unit metadata because the raw matrix availability export is inconsistent.
- Drop the demo tables with `DROP TABLE IF EXISTS demo_supply_catalogue_assets; DROP TABLE IF EXISTS demo_supply_catalogue_projects;` once the proper path exists.
- Delete this note once the production-ready catalogue path is in place.

## PropertyFinder listings demo shortcut

For the May 2026 demo, the listings page is populated from the PropertyFinder export in R2 using a capped one-time local import.

Current shortcut:
- Run `cd backend && uv run python -m scripts.listings.import_pf_listings_demo` to recreate the demo data.
- The script samples the latest available `raw/source=pf_listings` manifests, capped at 2,500 sale rows and 2,500 rental rows by default.
- The script creates a local Postgres table named `demo_pf_listings`.
- The API exposes `/api/v1/listings` and `/api/v1/listings/{listing_id}`.
- The frontend exposes `/listings` from the main navbar with a sale/rent toggle, filters, listing cards, and a detail panel.
- The demo page intentionally requests 24 cards at a time and uses the smaller PropertyFinder card thumbnail URL so the first screen stays responsive with remote third-party media.
- Listing images, floorplans, agent photos, and broker logos are direct PropertyFinder/static shared URLs from the raw export; they are not cached or proxied locally.
- This is intentionally not modeled as a durable ingestion pipeline, migration-backed production feature, or media pipeline.

After the demo:
- Move PropertyFinder ingestion into the proper data ingestion repo and decide whether this belongs in Postgres, ClickHouse, or a search index.
- Replace the local demo table with reviewed migrations or a warehouse-backed service.
- Replace direct third-party media URLs with a production-safe media/CDN strategy if listings become productized.
- Add pagination beyond the first page, richer filter facets, deduplication rules, and freshness/source quality checks.
- Drop the demo table with `DROP TABLE IF EXISTS demo_pf_listings;` once the proper path exists.
- Delete this note once the production-ready listings path is in place.
