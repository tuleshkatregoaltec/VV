"""Conservative, repeatable source-file chronology; never legal ownership proof."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.crm.identity import ParsedContact, _candidate_owner_key, _property_scopes_compatible
from app.crm.import_events import event_family
from app.crm.owner_projection import _property_identity

SOURCE_LIFECYCLE_VERSION = "source-lifecycle-1"
_BANK = re.compile(r"\b(?:bank|banking|bancorp)\b", re.IGNORECASE)
_COMPARABLE = {"sale", "unknown", "contact_snapshot"}
_REASONS = {
    "possible_financial_institution": "The supplied name contains a bank term; this may identify a financial institution, but does not prove a mortgage or its role.",
    "prior_acquisition_not_observed": "No earlier Buyer acquisition for this source Seller identity is observed in this file. A possible intermediary requires review; incomplete history or a different identity is also possible.",
    "amount_anomaly_possible_non_sale": "A strictly later event amount is at most 10% of a previous comparable property event. Review for a possible non-sale event or data error; this does not establish rental or mortgage activity.",
    "same_date_amount_conflict": "Different amounts occur on the same property date; row order cannot establish event order.",
    "latest_buyer_tie": "Different Buyer identities share the latest source date; coownership or unresolved event order requires review.",
    "later_event_review": "A same-day or later bank-name or amount-anomaly source event requires review before source-only ownership inference.",
    "later_unknown_lifecycle": "A later or undated source event has unknown lifecycle semantics; source chronology cannot establish the current owner.",
    "transfer_lifecycle_review": "A transfer, inheritance, gift, property change or lease-to-own event requires review before inferring ownership from a sale.",
    "unresolved_property_identity": "Source-only chronology requires an unambiguous unit and compatible property scope; this row is unresolved or identifies a cluster.",
    "inferred_dated_parties": "Dated Buyer/Seller with a positive amount is considered only under the documented dated-parties policy; its missing procedure is not a verified sale.",
}


def annotate_source_lifecycle(
    candidates: list[ParsedContact], *, policy: str = "explicit-sales"
) -> list[dict[str, Any]]:
    """Annotate in place and return JSON-safe row evidence in input order.

    No warehouse, DB or rental lookup is performed. ``dated-parties`` is an
    opt-in source-only inference, also respected when already documented in
    source_semantics_inference. It never changes the parsed event family.
    Evidence contains dates, amounts and roles, never contact names or channels.
    """
    if policy not in {"explicit-sales", "dated-parties"}:
        raise ValueError("Unsupported source lifecycle policy")
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    results: list[dict[str, Any]] = []
    eligible: dict[int, bool] = {}
    for i, candidate in enumerate(candidates):
        family = event_family(candidate.procedure_type)
        declared_family = candidate.evidence.get(
            "parsed_event_family", candidate.evidence.get("event_family")
        )
        if not candidate.procedure_type.strip() and declared_family in {
            "unknown",
            "financing",
            "rental",
            "lease_to_own",
            "gift",
            "inheritance",
            "ownership_transfer",
            "property_change",
        }:
            family = declared_family
        documented = candidate.evidence.get("source_semantics_inference", {}).get("policy")
        inferred = bool(
            (policy == "dated-parties" or documented == "dated-parties")
            and family == "contact_snapshot"
            and candidate.party_role in {"Buyer", "Seller"}
            and candidate.transaction_date
            and (candidate.transaction_price_aed or 0) > 0
        )
        evidence = {
            "version": SOURCE_LIFECYCLE_VERSION,
            "policy": "dated-parties" if inferred else policy,
            "event_family": family,
            "evidence_kind": "heuristic_source_only",
            "legal_ownership_proof": False,
            "transaction_date": candidate.transaction_date.isoformat()
            if candidate.transaction_date
            else None,
            "transaction_price_aed": candidate.transaction_price_aed,
            "party_role": candidate.party_role,
            "as_of_file": "not_assessed",
            "flags": [],
            "reasons": [],
        }
        results.append(evidence)
        candidate.evidence["source_lifecycle"] = evidence
        if _BANK.search(candidate.contact_name):
            evidence["flags"].append("possible_financial_institution")
        if inferred:
            evidence["flags"].append("inferred_dated_parties")
        eligible[i] = bool(
            (family == "sale" or inferred)
            and candidate.party_role in {"Buyer", "Seller"}
            and candidate.transaction_date
        )
        unresolved = (
            candidate.evidence.get("scoped_identity_collision")
            or candidate.evidence.get("source_identity_incomplete")
            or candidate.evidence.get("source_reference_kind")
            in {"cluster", "unresolved", "building_number_fallback"}
            or candidate.evidence.get("unit_number_fallback", {}).get("source_field")
            in {"buildingno", "building_no", "building_number"}
        )
        identity = _property_identity(
            {
                **vars(candidate),
                "property_key": candidate.property_key,
                # rematched claims carry their import only as the scope
                "import_id": candidate.evidence.get("source_import_scope", ""),
            }
        )
        if not identity or unresolved:
            evidence["flags"].append("unresolved_property_identity")
            continue
        # Never imply continuity between separate imported source files.
        source = str(
            candidate.evidence.get("source_import_scope")
            or candidate.evidence.get("source_filename")
            or ""
        )
        groups[(source, candidate.property_key)].append(i)

    def flag(index: int, name: str) -> None:
        if name not in results[index]["flags"]:
            results[index]["flags"].append(name)

    for indices in groups.values():
        scopes = {(candidates[i].area_name, candidates[i].project_name) for i in indices}
        if any(
            not _property_scopes_compatible(
                {"area_name": a, "project_name": p}, {"area_name": b, "project_name": q}
            )
            for a, p in scopes
            for b, q in scopes
        ):
            for i in indices:
                flag(i, "unresolved_property_identity")
            continue
        by_date: dict[Any, list[int]] = defaultdict(list)
        for i in indices:
            by_date[candidates[i].transaction_date].append(i)
        dates = sorted(day for day in by_date if day is not None)
        latest = dates[-1] if dates else None
        previous_amounts: list[int] = []
        previous_date = None
        earlier_buyers: set[str] = set()
        for day in dates:
            batch = by_date[day]
            amounts = sorted(
                {
                    candidates[i].transaction_price_aed
                    for i in batch
                    if (candidates[i].transaction_price_aed or 0) > 0
                    and results[i]["event_family"] in _COMPARABLE
                }
            )
            if len(amounts) > 1:
                for i in batch:
                    flag(i, "same_date_amount_conflict")
            for i in batch:
                candidate, evidence = candidates[i], results[i]
                evidence["latest_source_date"] = latest.isoformat() if latest else None
                if (
                    candidate.party_role == "Seller"
                    and _candidate_owner_key(candidate) not in earlier_buyers
                ):
                    flag(i, "prior_acquisition_not_observed")
                if (
                    previous_amounts
                    and evidence["event_family"] in _COMPARABLE
                    and (candidate.transaction_price_aed or 0) > 0
                    and candidate.transaction_price_aed * 10 <= max(previous_amounts)
                ):
                    flag(i, "amount_anomaly_possible_non_sale")
                    evidence["previous_comparable_date"] = previous_date.isoformat()
                    evidence["previous_comparable_amounts_aed"] = previous_amounts
            earlier_buyers.update(
                _candidate_owner_key(candidates[i])
                for i in batch
                if eligible[i] and candidates[i].party_role == "Buyer"
            )
            if amounts:
                previous_amounts, previous_date = amounts, day
        latest_acquisition = max(
            (candidates[i].transaction_date for i in indices if eligible[i]), default=None
        )
        latest_buyers = {
            _candidate_owner_key(candidates[i])
            for i in by_date.get(latest_acquisition, [])
            if eligible[i] and candidates[i].party_role == "Buyer"
        }
        for i in indices:
            candidate, evidence = candidates[i], results[i]
            if not eligible[i]:
                evidence["as_of_file"] = "uncertain"
                continue
            blockers = False
            for j in indices:
                other = candidates[j]
                if (
                    other.transaction_date is not None
                    and other.transaction_date < candidate.transaction_date
                ):
                    continue
                family = results[j]["event_family"]
                if family in {"unknown", "contact_snapshot"} and not eligible[j]:
                    flag(i, "later_unknown_lifecycle")
                    blockers = True
                if family in {
                    "gift",
                    "inheritance",
                    "ownership_transfer",
                    "property_change",
                    "lease_to_own",
                }:
                    flag(i, "transfer_lifecycle_review")
                    blockers = True
                if set(results[j]["flags"]) & {
                    "possible_financial_institution",
                    "amount_anomaly_possible_non_sale",
                    "same_date_amount_conflict",
                }:
                    flag(i, "later_event_review")
                    blockers = True
            if candidate.transaction_date == latest_acquisition and len(latest_buyers) > 1:
                flag(i, "latest_buyer_tie")
                blockers = True
            evidence["as_of_file"] = (
                "uncertain"
                if blockers
                else "possible_as_of_file"
                if candidate.party_role == "Buyer"
                and candidate.transaction_date == latest_acquisition
                else "historical_source_party"
            )
    for evidence in results:
        evidence["flags"] = sorted(evidence["flags"])
        evidence["reasons"] = [_REASONS[name] for name in evidence["flags"]]
    return results
