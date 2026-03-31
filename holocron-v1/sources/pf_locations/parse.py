"""Property Finder locations parsing helpers kept local to the source package."""

from __future__ import annotations

from dataclasses import dataclass
import json

from holocron.scrape.propertyfinder import extract_next_data


@dataclass(frozen=True)
class RawLocationRecord:
    purpose: str
    source_url: str
    pf_location_id: str
    location_name: str
    alternate_name: str
    path_ids: str
    path_names_en: str
    level_type: str
    slug: str
    city_slug: str
    is_transaction_visible: int
    is_community_visible: int
    is_subcommunity_visible: int
    is_in_cms: int
    breadcrumbs_json: str


@dataclass(frozen=True)
class PfLocationRow:
    release_id: str
    scraped_at: str
    pf_location_id: str
    parent_pf_location_id: str
    city_pf_location_id: str
    path_ids: str
    path_depth: int
    level_type: str
    location_name: str
    alternate_name: str
    slug: str
    city_slug: str
    parent_path_name_en: str
    full_path_name_en: str
    breadcrumbs_json: str
    is_transaction_visible: int
    is_community_visible: int
    is_subcommunity_visible: int
    is_in_cms: int
    seen_in_buy: int
    seen_in_rent: int
    buy_listing_url: str
    rent_listing_url: str


def extract_location_record(*, purpose: str, source_url: str, html: str) -> RawLocationRecord:
    payload = extract_next_data(html)
    page_props = payload["props"]["pageProps"]
    location = page_props["filtersValueFromQuery"]["filter[locations_ids]"][0]
    breadcrumbs = page_props.get("breadCrumbs", [])
    return RawLocationRecord(
        purpose=purpose,
        source_url=source_url,
        pf_location_id=str(location.get("id", "")).strip(),
        location_name=str(location.get("n", "")).strip(),
        alternate_name=str(location.get("a", "")).strip(),
        path_ids=str(location.get("p", "")).strip(),
        path_names_en=str(location.get("en_p_n", "")).strip(),
        level_type=str(location.get("l_t", "")).strip(),
        slug=str(location.get("en_s") or location.get("s") or "").strip(),
        city_slug=str(location.get("en_c_s", "")).strip(),
        is_transaction_visible=1 if bool(location.get("i_t_v")) else 0,
        is_community_visible=1 if bool(location.get("i_c_v")) else 0,
        is_subcommunity_visible=1 if bool(location.get("i_sc_v")) else 0,
        is_in_cms=1 if bool(location.get("is_in_cms")) else 0,
        breadcrumbs_json=json.dumps(breadcrumbs, ensure_ascii=False, separators=(",", ":")),
    )


def parent_id(path_ids: str) -> str:
    parts = [part for part in path_ids.split(".") if part]
    if len(parts) <= 1:
        return ""
    return parts[-2]


def city_id(path_ids: str) -> str:
    parts = [part for part in path_ids.split(".") if part]
    if not parts:
        return ""
    return parts[0]


def path_depth(path_ids: str) -> int:
    return len([part for part in path_ids.split(".") if part])


def full_path_name(record: RawLocationRecord) -> str:
    parent_names = record.path_names_en.strip()
    if not parent_names:
        return record.location_name
    return f"{parent_names}, {record.location_name}"


def merge_records(run_id: str, records: list[RawLocationRecord], *, scraped_at: str) -> list[PfLocationRow]:
    by_id: dict[str, list[RawLocationRecord]] = {}
    for record in records:
        by_id.setdefault(record.pf_location_id, []).append(record)

    rows: list[PfLocationRow] = []
    for pf_location_id in sorted(by_id, key=lambda value: (len(value), value)):
        grouped = by_id[pf_location_id]
        primary = sorted(
            grouped,
            key=lambda item: (
                path_depth(item.path_ids),
                item.purpose != "buy",
                len(item.breadcrumbs_json),
            ),
        )[0]
        breadcrumbs = []
        for item in grouped:
            if item.breadcrumbs_json and item.breadcrumbs_json != "[]":
                breadcrumbs = json.loads(item.breadcrumbs_json)
                break
        buy_url = next((item.source_url for item in grouped if item.purpose == "buy"), "")
        rent_url = next((item.source_url for item in grouped if item.purpose == "rent"), "")
        rows.append(
            PfLocationRow(
                release_id=run_id,
                scraped_at=scraped_at,
                pf_location_id=pf_location_id,
                parent_pf_location_id=parent_id(primary.path_ids),
                city_pf_location_id=city_id(primary.path_ids),
                path_ids=primary.path_ids,
                path_depth=path_depth(primary.path_ids),
                level_type=primary.level_type,
                location_name=primary.location_name,
                alternate_name=primary.alternate_name,
                slug=primary.slug,
                city_slug=primary.city_slug,
                parent_path_name_en=primary.path_names_en,
                full_path_name_en=full_path_name(primary),
                breadcrumbs_json=json.dumps(breadcrumbs, ensure_ascii=False, separators=(",", ":")),
                is_transaction_visible=max(item.is_transaction_visible for item in grouped),
                is_community_visible=max(item.is_community_visible for item in grouped),
                is_subcommunity_visible=max(item.is_subcommunity_visible for item in grouped),
                is_in_cms=max(item.is_in_cms for item in grouped),
                seen_in_buy=1 if any(item.purpose == "buy" for item in grouped) else 0,
                seen_in_rent=1 if any(item.purpose == "rent" for item in grouped) else 0,
                buy_listing_url=buy_url,
                rent_listing_url=rent_url,
            )
        )
    return rows
