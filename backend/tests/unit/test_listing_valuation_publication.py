"""A valuation rebuild must leave the last good release serving until replacement is complete."""

import sys
from unittest.mock import AsyncMock

import pytest

from scripts.listings import value_listings


@pytest.fixture
def publication(monkeypatch):
    state = {"failure": None, "tables": {value_listings.TABLE: [["previous"]]}, "commands": []}
    result = dict.fromkeys(value_listings.COLUMNS, 0)
    result.update(listing_id="new", estimate_aed=2_000_000, market_position="below_market")

    class Client:
        async def command(self, sql):
            sql = sql.strip()
            state["commands"].append(sql)
            if sql.startswith("CREATE TABLE IF NOT EXISTS"):
                return
            if sql.startswith("CREATE TABLE"):
                state["tables"][sql.split()[2]] = []
            elif sql.startswith("EXCHANGE TABLES"):
                if state["failure"] == "exchange":
                    raise RuntimeError("exchange failed")
                serving, staging = sql.split()[2::2]
                state["tables"][serving], state["tables"][staging] = (
                    state["tables"][staging],
                    state["tables"][serving],
                )
            else:
                raise AssertionError(f"Unsafe or unexpected publication command: {sql}")

        async def insert(self, table, rows, *, column_names):
            assert table != value_listings.TABLE
            assert state["tables"][value_listings.TABLE] == [["previous"]]
            if state["failure"] == "insert":
                raise RuntimeError("insert failed")
            state["tables"][table] = rows

    async def query(sql):
        rows = state["tables"][sql.split()[-1]]
        assert state["tables"][value_listings.TABLE] == [["previous"]]
        n = 0 if state["failure"] == "validation" else len(rows)
        ids = 0 if state["failure"] == "duplicates" else len(rows)
        return [{"n": n, "ids": ids}]

    monkeypatch.setattr(value_listings, "_rows", AsyncMock(return_value=[{"listing_id": "new"}]))
    monkeypatch.setattr(value_listings, "value_listing_rows", AsyncMock(return_value=[result]))
    monkeypatch.setattr(value_listings, "get_client", AsyncMock(return_value=Client()))
    monkeypatch.setattr(value_listings, "close_clickhouse", AsyncMock())
    monkeypatch.setattr(value_listings, "query", query)
    monkeypatch.setattr(sys, "argv", ["value_listings.py"])
    return state


@pytest.mark.parametrize("failure", ["insert", "validation", "duplicates", "exchange"])
async def test_failed_replacement_keeps_previous_valuation_release(publication, failure):
    publication["failure"] = failure
    with pytest.raises(RuntimeError):
        await value_listings.main()
    assert publication["tables"][value_listings.TABLE] == [["previous"]]
    assert not any("TRUNCATE" in sql or "DROP" in sql for sql in publication["commands"])
    value_listings.close_clickhouse.assert_awaited_once()


async def test_success_exchanges_validated_release_and_retains_previous(publication):
    await value_listings.main()
    assert publication["tables"][value_listings.TABLE][0][0] == "new"
    retained = [
        rows for table, rows in publication["tables"].items() if table != value_listings.TABLE
    ]
    assert retained == [[["previous"]]]
    assert publication["commands"][-1].startswith("EXCHANGE TABLES")


@pytest.mark.parametrize("args", [["--limit", "1"], ["--dry-run"], ["--limit", "1", "--dry-run"]])
async def test_quick_checks_never_replace_the_full_publication(publication, monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["value_listings.py", *args])
    await value_listings.main()
    assert publication["tables"] == {value_listings.TABLE: [["previous"]]}
    value_listings.get_client.assert_not_awaited()


@pytest.mark.parametrize("limit", ["0", "-1"])
async def test_nonpositive_limit_is_rejected_before_reading_or_writing(
    publication, monkeypatch, limit
):
    monkeypatch.setattr(sys, "argv", ["value_listings.py", "--limit", limit])
    with pytest.raises(SystemExit) as error:
        await value_listings.main()
    assert error.value.code == 2
    value_listings._rows.assert_not_awaited()
    value_listings.get_client.assert_not_awaited()
