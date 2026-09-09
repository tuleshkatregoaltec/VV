import gzip
import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(profile_id: str, configuration_hash: str) -> dict:
    return {
        "source_account": "account-b",
        "filter_profile": {"id": profile_id},
        "source_location": {"id": "1", "text": "Dubai", "slug": "dubai"},
        "configuration_hash": configuration_hash,
        "shard": {"date": "2026-07-01"},
        "columns": [
            {
                "id": "PATH_NAME",
                "text": "L-07, Greece Cluster, International City Apartment, No. 1204",
            },
            {"id": "PROP_SIZES", "text": "1 Bed 732 sqft"},
            {"id": "TOTAL_PRICES", "text": "38,000 Renewed"},
            {"id": "START_DATE", "text": "1 Jul, 2026 - 30 Jun, 2027 12 Months"},
        ],
    }


class FakeClient:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, list[list[object]], list[str]]] = []

    def insert(self, table: str, rows: list[list[object]], *, column_names: list[str]) -> None:
        self.inserts.append((table, rows, column_names))


def test_loader_reconciles_profile_union_before_insert(tmp_path: Path) -> None:
    loader = _load_script("load_dxbi_rental_events.py")
    broad_path = tmp_path / "profile=broad" / "location=1" / "date=2026-07-01" / "a.jsonl.gz"
    leaf_path = tmp_path / "profile=leaf" / "location=1" / "date=2026-07-01" / "b.jsonl.gz"
    broad_path.parent.mkdir(parents=True)
    leaf_path.parent.mkdir(parents=True)
    with gzip.open(broad_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(_payload("broad", "12345678901234567890")) + "\n")
    with gzip.open(leaf_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(_payload("leaf", "abcdefghijklmnopqrst")) + "\n")
    client = FakeClient()

    totals = loader.load_files(
        [broad_path, leaf_path],
        client=client,
        min_start_date=date(2025, 1, 1),
        batch_size=100,
    )

    assert totals == {
        "raw_rows": 2,
        "unique_source_rows": 1,
        "normalized_rows": 2,
        "quarantined_rows": 0,
        "profile_overlap_rows": 1,
        "loaded_contracts": 1,
        "out_of_scope_rows": 0,
    }
    assert len(client.inserts) == 1
    table, rows, columns = client.inserts[0]
    assert table == "dxbi_rental_events_v2"
    assert len(rows) == 1
    assert rows[0][columns.index("unit_number")] == "1204"
    assert rows[0][columns.index("source_account")] == "account-b"


def test_loader_quarantines_malformed_json_and_preserves_accounting(tmp_path: Path) -> None:
    loader = _load_script("load_dxbi_rental_events.py")
    path = tmp_path / "date=2026-07-01" / "bad.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{bad json\n")
    quarantine = tmp_path / "quarantine.jsonl"

    totals = loader.load_files(
        [path],
        client=FakeClient(),
        min_start_date=date(2025, 1, 1),
        batch_size=100,
        quarantine_path=quarantine,
    )

    assert totals["raw_rows"] == 1
    assert totals["normalized_rows"] == 0
    assert totals["quarantined_rows"] == 1
    assert quarantine.exists()
