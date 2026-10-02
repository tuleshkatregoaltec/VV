"""Trusted execution context and explicit limits of the current data contract.

Chat2 must supply an immutable release handle and authoritative source/period coverage
before cross-source comparisons can be published. Observation timestamps are not release
IDs. In particular, unchanged timestamps do not prove atomic publication.
"""

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date

from app.clickhouse.client import bounded_queries

COVERAGE_NOTE = (
    "Coverage is unverified: minimum/maximum event dates describe observed records, "
    "not ingestion completeness. No authoritative source/period coverage contract is available."
)
RELEASE_NOTE = (
    "No immutable, shared release handle is available. Observation timestamps are not release "
    "IDs and cannot guarantee atomic consistency; cross-source conclusions are withheld."
)


@dataclass(frozen=True, slots=True)
class MarketAccessContext:
    user_id: str
    organization_id: str
    reference_date: date
    execution_id: str

    def __post_init__(self):
        if not self.user_id or not self.organization_id or not self.execution_id:
            raise ValueError("An authenticated market execution context is required")


@contextmanager
def bounded_market_read():
    """Bound server work as well as the caller's asynchronous deadline."""
    with bounded_queries(max_execution_time=15, max_result_rows=1000, max_result_bytes=262144):
        yield


@dataclass(frozen=True, slots=True)
class SourceCoverage:
    source: str
    start: date
    end: date
    status: str


@dataclass(frozen=True, slots=True)
class MarketRelease:
    """An application-owned lease over immutable source versions, never model input.

    The provider must keep all domain queries on these versions for the entire context
    lifetime. A timestamp or checking mutable views before/after does NOT meet this contract.
    Source names: sales, rentals, listings, projects. Coverage comes from verified ingestion
    manifests, not min/max event dates. Tests use immutable disposable fixture databases.
    """

    release_id: str
    sources: frozenset[str]
    coverage: tuple[SourceCoverage, ...] = ()

    def covers(self, source: str, start: date, end: date) -> bool:
        return source in self.sources and any(
            item.source == source
            and item.status == "complete"
            and item.start <= start
            and item.end >= end
            for item in self.coverage
        )


# The canonical publisher has not yet exported a lease. This is the single read-only
# integration seam for Chat2: replace the provider with its snapshot-pinning context,
# retaining the lease through cancellation/cleanup. Never fabricate a lease from built_at.
_release: ContextVar[MarketRelease | None] = ContextVar("market_release", default=None)


@asynccontextmanager
async def acquire_market_release(context: MarketAccessContext):
    yield None


@contextmanager
def use_market_release(release: MarketRelease | None):
    token = _release.set(release)
    try:
        yield
    finally:
        _release.reset(token)


def current_market_release() -> MarketRelease | None:
    return _release.get()


def has_shared_release(*sources: str) -> bool:
    release = current_market_release()
    return bool(release and release.release_id and set(sources) <= release.sources)
