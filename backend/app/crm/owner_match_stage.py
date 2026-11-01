"""The import stage that runs the property-first matcher and stores each row's verdict.

It sits between the legacy lookups (property keys, leases, lifecycle) and ``_apply_evidence``,
which turns the stored verdict into an ownership status. A new import, a replay and a rematch of
saved claims all pass through it, so they cannot disagree.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.core.async_work import run_in_thread
from app.crm.brokers import BrokerIndex, annotate_broker_contacts
from app.crm.identity import ParsedContact
from app.crm.import_parsing import matcher_source_from_evidence
from app.crm.owner_match_loader import load_sales_index, match_sources
from app.crm.owner_match_status import owner_match_evidence
from app.crm.owner_matcher import MatchResult, SalesIndex, later_sale_date


def candidate_source(candidate: ParsedContact) -> dict[str, str]:
    """The matcher's input for a row: stored at parse time, or rebuilt for an older claim.

    A rebuilt source is stored for the summary but rebuilt again on every rematch, so a fix to the
    rebuild reaches claims that were already rematched."""
    stored = candidate.evidence.get("matcher_source")
    if isinstance(stored, dict) and not candidate.evidence.get("matcher_source_rebuilt"):
        return stored
    return matcher_source_from_evidence(
        candidate.evidence,
        transaction_date=candidate.transaction_date,
        transaction_price_aed=candidate.transaction_price_aed,
        procedure_type=candidate.procedure_type,
        area_name=candidate.area_name,
        project_name=candidate.project_name,
        building_name=candidate.building_name,
        unit_number=candidate.unit_number,
        property_type=candidate.property_type,
    )


def _match_import(
    index: SalesIndex, sources: list[dict[str, str]]
) -> list[tuple[MatchResult, str | None]]:
    results = match_sources(index, sources)
    later: dict[int, str | None] = {}
    return [
        (result, later.setdefault(id(result), later_sale_date(index, result))) for result in results
    ]


async def run_owner_matching(
    candidates: list[ParsedContact], brokers: BrokerIndex | None = None
) -> None:
    """Store ``evidence["owner_match"]`` (and the source it was matched from) on every row.

    Rows are matched per import (``source_import_scope``; a new import is one scope), because the
    learned unit aliases belong to the import they were read from. ``brokers`` (loaded once by the
    caller; an empty index applies no rule and clears old marks) sets ``evidence["broker_contact"]``;
    None leaves the rows' stored marks alone."""
    if brokers is not None:
        annotate_broker_contacts(candidates, brokers)
    scopes: dict[str, list[ParsedContact]] = defaultdict(list)
    for candidate in candidates:
        scopes[str(candidate.evidence.get("source_import_scope") or "")].append(candidate)
    for group in scopes.values():
        sources = [candidate_source(candidate) for candidate in group]
        index = await load_sales_index(sources)
        verdicts = await run_in_thread(_match_import, index, sources)
        del index
        for candidate, source, (result, later) in zip(group, sources, verdicts, strict=True):
            if "matcher_source" not in candidate.evidence or candidate.evidence.get(
                "matcher_source_rebuilt"
            ):
                candidate.evidence["matcher_source_rebuilt"] = True
            candidate.evidence["matcher_source"] = source
            candidate.evidence["owner_match"] = owner_match_evidence(result, later_sale_date=later)


def stored_verdicts(candidates: list[ParsedContact]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(verdict, source) of every row that has one, for the import summary."""
    return [
        (candidate.evidence["owner_match"], candidate_source(candidate))
        for candidate in candidates
        if isinstance(candidate.evidence.get("owner_match"), dict)
    ]
