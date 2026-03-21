"""Property Finder location hierarchy extraction logic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, fields
from pathlib import Path

from holocron.framework.csv_utils import write_csv
from holocron.framework.models import DownloadResult, utc_now_sql
from holocron.scrape.propertyfinder import collect_location_urls, fetch_text
from holocron.sources.pf_locations.parse import (
    PfLocationRow,
    RawLocationRecord,
    extract_location_record,
    merge_records,
)

_utc_now_sql = utc_now_sql


def _fetch_record(http, *, purpose: str, url: str) -> RawLocationRecord:
    html = fetch_text(http, url)
    return extract_location_record(purpose=purpose, source_url=url, html=html)


def _collect_location_urls(http, *, purpose: str, max_pages_per_purpose: int | None) -> list[str]:
    return collect_location_urls(
        http,
        purpose=purpose,
        max_pages_per_purpose=max_pages_per_purpose,
    )


def download_all(
    *,
    dest_dir: Path,
    run_id: str,
    http,
    max_pages_per_purpose: int | None = None,
    worker_count: int = 8,
    context=None,
) -> list[DownloadResult]:
    urls_by_purpose = {
        purpose: _collect_location_urls(
            http,
            purpose=purpose,
            max_pages_per_purpose=max_pages_per_purpose,
        )
        for purpose in ("buy", "rent")
    }
    if context is not None:
        for purpose, urls in urls_by_purpose.items():
            context.log.info(f"pf_locations: queued {len(urls)} {purpose} listing location pages")

    tasks = [(purpose, url) for purpose in ("buy", "rent") for url in urls_by_purpose[purpose]]
    records: list[RawLocationRecord] = []
    with ThreadPoolExecutor(max_workers=max(1, worker_count)) as executor:
        future_map = {
            executor.submit(_fetch_record, http, purpose=purpose, url=url): (purpose, url)
            for purpose, url in tasks
        }
        for index, future in enumerate(as_completed(future_map), start=1):
            purpose, url = future_map[future]
            record = future.result()
            records.append(record)
            if context is not None and (index <= 5 or index % 250 == 0):
                context.log.info(
                    f"pf_locations: fetched {index}/{len(tasks)} location pages; "
                    f"latest={purpose}:{record.slug}"
                )

    rows = merge_records(run_id, records, scraped_at=_utc_now_sql())
    csv_path = dest_dir / "pf_locations.csv"
    fieldnames = [field.name for field in fields(PfLocationRow)]
    write_csv(csv_path, fieldnames, (asdict(row) for row in rows))
    if context is not None:
        context.log.info(f"pf_locations: wrote {len(rows):,} unique locations to {csv_path.name}")
    return [DownloadResult(canonical_name=csv_path.name, local_path=csv_path)]
