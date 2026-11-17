"""A release build must not be able to take the whole ClickHouse container.

Measured on the 9 GiB production box: the sale events INSERT used 7.0 GiB (59 threads, no
settings) and the rental events INSERT 4.9 GiB, while user queries share the same server.
Every INSERT of a release build therefore carries a hard per-query memory cap, one insert
stream and bounded external sort/group-by thresholds; the two events inserts (the widest
joins) also run on few threads.
"""

from __future__ import annotations

import re

import pytest

from holocron.market import transforms as t

_BUILDS = {
    "sale_matches": t.SALE_MATCH_STATEMENTS,
    "geo_crosswalk": t._GEO_CROSSWALK_STATEMENTS,
    "sale_events": (t._SALE_EVENTS_DLD_SQL, t._SALE_EVENTS_DXBI_SQL),
    "rental_matches": t._RENTAL_MATCH_STATEMENTS,
    "rental_events": (t._RENTAL_EVENTS_DLD_SQL, t._RENTAL_EVENTS_DXBI_SQL),
}
_INSERTS = [
    pytest.param(build, statement, id=f"{build}-{index}")
    for build, statements in _BUILDS.items()
    for index, statement in enumerate(statements)
    if statement.lstrip().upper().startswith("INSERT")
]
_CAP_BYTES = 9 * 1024**3 * 0.75  # a build may use at most three quarters of the container


def _setting(statement: str, name: str) -> int:
    found = re.search(rf"\b{name}\s*=\s*(\d+)", statement.split("SETTINGS")[-1])
    assert found, f"{name} is not set on the statement's SETTINGS clause"
    return int(found.group(1))


@pytest.mark.parametrize(("build", "statement"), _INSERTS)
def test_every_release_insert_is_memory_bounded(build: str, statement: str) -> None:
    assert "SETTINGS" in statement, f"{build}: an INSERT ... SELECT without SETTINGS"
    assert _setting(statement, "max_memory_usage") <= _CAP_BYTES
    assert _setting(statement, "max_insert_threads") == 1
    assert _setting(statement, "max_bytes_before_external_sort") <= 500_000_000
    assert _setting(statement, "max_bytes_before_external_group_by") <= 500_000_000


@pytest.mark.parametrize("build", ["sale_events", "rental_events"])
def test_events_inserts_run_on_few_threads(build: str) -> None:
    limit = 2 if build == "sale_events" else 4
    for statement in _BUILDS[build]:
        assert _setting(statement, "max_threads") <= limit


def test_there_are_inserts_to_check() -> None:
    assert len(_INSERTS) > 40
