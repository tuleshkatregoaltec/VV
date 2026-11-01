"""An offline replay must relocate cleanly without mutating its historical baseline."""

import ast
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from scripts.crm.owner_recovery_experiment import cli, namespace_delivery


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def private_fixture(tmp_path):
    data = tmp_path / "private"
    experiment = data / "experiment"
    dxbi = data / "dxbi"
    experiment.mkdir(parents=True)
    dxbi.mkdir()
    (experiment / "engine-training-pairs.jsonl").write_text('{"weak_pair":"unchanged"}\n')
    (experiment / "rows.jsonl").write_text('{"original_row":"unchanged"}\n')
    (dxbi / "places-snapshot.json").write_text("[]")
    with sqlite3.connect(dxbi / "snapshot.sqlite") as database:
        database.execute("CREATE TABLE event(family TEXT, amount REAL, payload TEXT)")
    archive = tmp_path / "archive"
    scripts = archive / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "engine.py").write_text(
        "SNAPSHOT='/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite'\n"
        "PLACES='/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json'\n"
    )
    (scripts / "aliases.py").write_text("# frozen alias fixture\n")
    (scripts / "community_fingerprint.py").write_text("RULES={'uncapped':True}\n")
    (scripts / "prepare.py").write_text("raise RuntimeError('must never be executable via CLI')\n")
    (scripts / "engine-namespace-positive-control.py").write_text(
        "from pathlib import Path\n"
        "root=Path(__file__).parent\n"
        "assert (root/'engine-training-pairs.jsonl').read_text()\n"
        "(root/'proof.json').write_text('PASS')\n"
    )
    (archive / "frozen_backend/app").mkdir(parents=True)
    (archive / "frozen_backend/app/__init__.py").write_text("")
    (archive / "frozen_analytics").mkdir()
    (archive / "frozen_analytics/geography.py").write_text("# frozen geography\n")
    files = {
        str(path.relative_to(archive)): {"sha256": fingerprint(path), "bytes": path.stat().st_size}
        for path in archive.rglob("*.py")
    }
    (archive / "manifest.json").write_text(json.dumps({"files": files}))
    return cli.paths(data), archive, tmp_path / "new-run"


def test_defaults_do_not_depend_on_calling_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.resolve_path(Path(".local/example")) == cli.PROJECT / ".local/example"
    assert cli.DEFAULT_DATA == cli.PROJECT / ".local/owner-recovery/2026-10-29"
    assert cli.paths(cli.DEFAULT_DATA)["snapshot"] == cli.DEFAULT_DATA / "dxbi/snapshot.sqlite"


def test_staging_relocates_executable_sources_and_preserves_originals(private_fixture):
    config, archive, run = private_fixture
    before = fingerprint(archive / "scripts/engine.py")
    source = config["experiment"] / "engine-training-pairs.jsonl"
    source_hash = fingerprint(source)
    result = cli.stage(config, run, lightweight=True, archive=archive)
    assert result["check"] == "PASS"
    text = (run / "engine.py").read_text()
    assert "/tmp/vv-" not in text
    assert str(config["snapshot"]) in text
    assert str(config["places"]) in text
    assert fingerprint(archive / "scripts/engine.py") == before
    assert fingerprint(source) == source_hash
    assert source.stat().st_ino != (run / source.name).stat().st_ino
    assert not (run / "prepare.py").exists()
    manifest = json.loads((run / "alias-dependency-manifest.json").read_text())
    assert manifest["files"]["frozen_analytics/geography.py"] == fingerprint(
        run / "frozen_analytics/geography.py"
    )


def test_existing_or_baseline_destinations_are_rejected_before_writing(private_fixture):
    config, archive, run = private_fixture
    baseline = config["experiment"] / "rows.jsonl"
    before = fingerprint(baseline)
    run.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        cli.stage(config, run, lightweight=True, archive=archive)
    with pytest.raises(ValueError, match="cached baseline"):
        cli.stage(config, config["experiment"] / "nested", lightweight=True, archive=archive)
    assert fingerprint(baseline) == before
    assert not (config["experiment"] / "nested").exists()


def test_real_subprocess_proof_writes_only_to_fresh_run(private_fixture):
    config, archive, run = private_fixture
    source = config["experiment"] / "engine-training-pairs.jsonl"
    before = fingerprint(source)
    cli.stage(config, run, lightweight=True, archive=archive)
    cli.execute(run, "proof")
    assert (run / "proof.json").read_text() == "PASS"
    assert fingerprint(source) == before
    assert not (config["experiment"] / "proof.json").exists()
    environment = cli.offline_environment(run)
    assert environment["POSTGRES_URL"].endswith("127.0.0.1:9/offline")
    assert environment["AI_TELEMETRY_ENABLED"] == "false"
    with pytest.raises(ValueError, match="Unknown offline profile"):
        cli.execute(run, "prepare")
    with pytest.raises(ValueError, match="Replay main first"):
        cli.execute(run, "audit")


def test_cached_index_metadata_is_relocated_only_in_independent_copy(private_fixture, monkeypatch):
    config, archive, run = private_fixture
    index = config["experiment"] / "community-index.sqlite"
    with sqlite3.connect(index) as database:
        database.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
        database.executemany(
            "INSERT INTO metadata VALUES(?,?)",
            [
                (name, "historical")
                for name in (
                    "snapshot_path",
                    "snapshot_size",
                    "snapshot_mtime",
                    "rules",
                    "code",
                    "places",
                )
            ],
        )
    identity = {
        "files": {
            "snapshot.sqlite": {"sha256": fingerprint(config["snapshot"])},
            "places-snapshot.json": {"sha256": fingerprint(config["places"])},
            "community-index.sqlite": {"sha256": fingerprint(index)},
        }
    }
    (archive / "input-identity.json").write_text(json.dumps(identity))
    before = fingerprint(index)
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: None)
    cli.stage(config, run, archive=archive)
    assert fingerprint(index) == before
    with sqlite3.connect(run / index.name) as database:
        metadata = dict(database.execute("SELECT key,value FROM metadata"))
    assert metadata["snapshot_path"] == str(config["snapshot"])
    assert metadata["code"] == fingerprint(run / "community_fingerprint.py")
    assert index.stat().st_ino != (run / index.name).stat().st_ino


@pytest.mark.parametrize("changed", ["snapshot", "places"])
def test_different_dataset_or_catalogue_cannot_bless_a_stale_index(
    private_fixture, monkeypatch, changed
):
    config, archive, run = private_fixture
    index = config["experiment"] / "community-index.sqlite"
    with sqlite3.connect(index) as database:
        database.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
        database.execute("INSERT INTO metadata VALUES('snapshot_path','historical')")
    (config["experiment"] / "community-summary.json").write_text('{"cached":"old dataset"}')
    identity = {
        "files": {
            "snapshot.sqlite": {"sha256": fingerprint(config["snapshot"])},
            "places-snapshot.json": {"sha256": fingerprint(config["places"])},
            "community-index.sqlite": {"sha256": fingerprint(index)},
        }
    }
    (archive / "input-identity.json").write_text(json.dumps(identity))
    baseline_hash = fingerprint(index)
    overrides = run.parent / "alternate-inputs"
    overrides.mkdir()
    if changed == "snapshot":
        original = config["snapshot"]
        replacement = overrides / "different-snapshot.sqlite"
        shutil.copy2(original, replacement)
        with sqlite3.connect(replacement) as database:
            database.execute("INSERT INTO event VALUES('sale',100,'{}')")
        os.utime(replacement, ns=(original.stat().st_atime_ns, original.stat().st_mtime_ns))
        assert replacement.stat().st_size == original.stat().st_size
        config = {**config, "snapshot": replacement}
    else:
        replacement = overrides / "different-places.json"
        replacement.write_text('[{"area_label":"Different catalogue"}]')
        config = {**config, "places": replacement}
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: None)
    cli.stage(config, run, archive=archive)
    manifest = json.loads((run / "stage-manifest.json").read_text())
    assert manifest["index_rebuild_required_at_stage"]
    assert not manifest["cached_index_identity"]["reusable"]
    assert not (run / "community-index.sqlite").exists()
    assert not (run / "community-summary.json").exists()
    assert fingerprint(index) == baseline_hash
    with pytest.raises(ValueError, match="Replay community first"):
        cli.execute(run, "c2")


def test_same_content_at_another_path_is_safe_to_reuse(private_fixture):
    config, archive, run = private_fixture
    index = config["experiment"] / "community-index.sqlite"
    index.write_bytes(b"private index identity fixture")
    (archive / "input-identity.json").write_text(
        json.dumps(
            {
                "files": {
                    "snapshot.sqlite": {"sha256": fingerprint(config["snapshot"])},
                    "places-snapshot.json": {"sha256": fingerprint(config["places"])},
                    "community-index.sqlite": {"sha256": fingerprint(index)},
                }
            }
        )
    )
    replacement = run.parent / "same-snapshot.sqlite"
    shutil.copy2(config["snapshot"], replacement)
    assert cli.index_identity({**config, "snapshot": replacement}, archive)["reusable"]


def test_sequential_community_then_c2_freezes_the_new_summary(private_fixture):
    config, archive, run = private_fixture
    experiment = config["experiment"]
    (experiment / "baseline-matched.jsonl").write_text("{}\n")
    (experiment / "community-summary.json").write_text('{"elapsed_seconds":1}')
    old_summary_hash = fingerprint(experiment / "community-summary.json")
    for name in (
        "community-frozen-rules.json",
        "community-input-manifest.json",
        "community-c2-frozen-rules.json",
        "community-c2-input-manifest.json",
    ):
        (experiment / name).write_text('{"inherited":"old summary"}')
    index = experiment / "community-index.sqlite"
    with sqlite3.connect(index) as database:
        database.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
        database.executemany(
            "INSERT INTO metadata VALUES(?,?)",
            [
                (name, "historical")
                for name in (
                    "snapshot_path",
                    "snapshot_size",
                    "snapshot_mtime",
                    "rules",
                    "code",
                    "places",
                )
            ],
        )
    (archive / "input-identity.json").write_text(
        json.dumps(
            {
                "files": {
                    "snapshot.sqlite": {"sha256": fingerprint(config["snapshot"])},
                    "places-snapshot.json": {"sha256": fingerprint(config["places"])},
                    "community-index.sqlite": {"sha256": fingerprint(index)},
                }
            }
        )
    )
    c1 = """import hashlib,json
from pathlib import Path
ROOT=Path(__file__).parent
RULES={'uncapped':True}
PLACES=Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json')
class Frozen:
 def digest(self,value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
frozen=Frozen()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(name,value):(ROOT/name).write_text(json.dumps(value))
def freeze():
 save('community-frozen-rules.json',RULES)
 save('community-input-manifest.json',{'code':sha(__file__)})
if __name__=='__main__':
 freeze()
 save('community-summary.json',{'elapsed_seconds':99})
"""
    (archive / "scripts/community_fingerprint.py").write_text(c1)
    # Exercise the historical C2 freeze function itself, without its expensive
    # matcher loop: the bug concerns pinning the C1 summary before C1 replay.
    original = (cli.ARCHIVE / "scripts/community-c2.py").read_text()
    function = next(
        node
        for node in ast.parse(original).body
        if isinstance(node, ast.FunctionDef) and node.name == "freeze"
    )
    freeze = ast.get_source_segment(original, function)
    c2 = (
        """import json
from pathlib import Path
import community_fingerprint as c1
ROOT=Path(__file__).parent
RULES=c1.RULES
def save(name,value):c1.save('community-c2-'+name,value)
"""
        + freeze
        + "\nif __name__=='__main__':freeze()\n"
    )
    (archive / "scripts/community-c2.py").write_text(c2)
    manifest = json.loads((archive / "manifest.json").read_text())
    manifest["files"] = {
        str(path.relative_to(archive)): {"sha256": fingerprint(path), "bytes": path.stat().st_size}
        for path in archive.rglob("*.py")
    }
    (archive / "manifest.json").write_text(json.dumps(manifest))
    cli.stage(config, run, archive=archive)
    assert not list(run.glob("community*input-manifest.json"))
    assert not list(run.glob("community*frozen-rules.json"))
    cli.execute(run, "community")
    assert fingerprint(run / "community-summary.json") != old_summary_hash
    assert not (run / "community-c2-input-manifest.json").exists()
    cli.execute(run, "c2")
    c2_inputs = json.loads((run / "community-c2-input-manifest.json").read_text())
    assert c2_inputs[str(run / "community-summary.json")] == fingerprint(
        run / "community-summary.json"
    )
    assert fingerprint(experiment / "community-summary.json") == old_summary_hash


def test_missing_data_and_archive_tampering_fail_loudly(private_fixture):
    config, archive, _ = private_fixture
    config["places"].unlink()
    result = cli.doctor(config, archive=archive)
    assert result["check"] == "FAIL"
    assert str(config["places"]) in result["missing"]
    (archive / "scripts/aliases.py").write_text("changed")
    with pytest.raises(ValueError, match="Archived source differs"):
        cli.archive_check(archive)


def test_namespace_delivery_preserves_date_conflicts_as_separate_tier(tmp_path):
    rows = []
    for index, gap in enumerate((0, 900)):
        row = {
            key: key
            for key in (
                "row_key",
                "filename",
                "sheet",
                "row",
                "source_event_id",
                "source_unit_id",
                "original_category",
                "primary_cause",
                "source",
                "raw_fields",
            )
        }
        row.update(
            row_key=str(index), status="conditional_existing_namespace_proposal", normalization=[]
        )
        row["selected"] = {
            "event_key": "sale:event",
            "property": ["area", "building", "1"],
            "target": {},
            "date": {
                "exact": gap == 0,
                "gap_days": gap,
                "source": "2020-01-01",
                "target": "2022-06-19",
            },
        }
        rows.append(row)
    (tmp_path / "engine-namespace-all.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    summary = namespace_delivery.export(tmp_path)
    delivered = [json.loads(line) for line in (tmp_path / "engine-namespace-delivery.jsonl").open()]
    assert summary["risk_tiers"] == {
        "conditional_namespace_exact": 1,
        "conditional_namespace_date_relaxed": 1,
    }
    assert delivered[1]["requires_date_review"] is True
    assert delivered[1]["date_gap_days"] == 900
    assert delivered[1]["raw_fields"] == rows[1]["raw_fields"]
    assert all(not row["conservative_new_recovery"] for row in delivered)
