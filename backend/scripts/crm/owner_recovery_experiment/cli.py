"""Stage and replay the private, offline 2026-10-29 experiment safely."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
PROJECT = PACKAGE.parents[3]
ARCHIVE = PACKAGE / "archive"
DEFAULT_DATA = PROJECT / ".local/owner-recovery/2026-10-29"
HISTORICAL_ONLY = {
    "prepare.py",
    "check_database.py",
    "package.py",
    "final_package_check.py",
    "verifier-deliverable.py",
    "alias-audit.py",
    "price_boundary.py",
}
PROFILES = {
    "proof": "engine-namespace-positive-control.py",
    "namespace": "engine-namespace-all.py",
    "namespace-delivery": "namespace_delivery.py",
    "community": "community_fingerprint.py",
    "c2": "community-c2.py",
    "c3": "community-c3.py",
    "c4": "community-c4.py",
    "c5": "community-c5.py",
    "community-combine": "community-combine.py",
    "combine": "combine_profiles.py",
    "main": "engine.py",
    "safety": "engine-safety.py",
    "audit": "engine-audit.py",
    "roles": "engine-role-indexed.py",
}
LIGHT_INPUTS = {"engine-training-pairs.jsonl"}
REBUILD_INPUTS = LIGHT_INPUTS | {
    "rows.jsonl",
    "all-rows.jsonl",
    "baseline-matched.jsonl",
    "label-sequence-evidence.json",
    "engine-role-reconciliation-declaration.json",
    "engine-safety-declaration.json",
}
INDEX_PROFILES = {"c2", "c3", "c4", "c5", "community-combine", "combine"}


def sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def resolve_path(path: Path) -> Path:
    path = path.expanduser()
    return (path if path.is_absolute() else PROJECT / path).resolve()


def paths(data_root: Path, snapshot: Path | None = None, places: Path | None = None) -> dict:
    data_root = resolve_path(data_root)
    return {
        "data_root": data_root,
        "experiment": data_root / "experiment",
        "snapshot": resolve_path(snapshot or data_root / "dxbi/snapshot.sqlite"),
        "places": resolve_path(places or data_root / "dxbi/places-snapshot.json"),
    }


def archive_check(archive: Path = ARCHIVE) -> dict:
    manifest = json.loads((archive / "manifest.json").read_text())
    for relative, expected in manifest["files"].items():
        if sha(archive / relative) != expected["sha256"]:
            raise ValueError(f"Archived source differs: {relative}")
    if (
        manifest.get("input_identity_sha256")
        and sha(archive / "input-identity.json") != manifest["input_identity_sha256"]
    ):
        raise ValueError("Archived input identity differs")
    return {"verified_archive_sources": len(manifest["files"])}


def index_identity(config: dict, archive: Path) -> dict:
    """Path/size/mtime do not prove that a cached retrieval index is reusable."""
    reference = archive / "input-identity.json"
    if not reference.is_file():
        return {"reusable": False, "reason": "no_frozen_content_identity"}
    expected = json.loads(reference.read_text())["files"]
    candidates = {
        "snapshot.sqlite": config["snapshot"],
        "places-snapshot.json": config["places"],
        "community-index.sqlite": config["experiment"] / "community-index.sqlite",
    }
    observed = {name: sha(path) if path.is_file() else None for name, path in candidates.items()}
    mismatches = [
        name for name, value in observed.items() if value != expected.get(name, {}).get("sha256")
    ]
    return {
        "reusable": not mismatches,
        "reason": "content_identity_verified" if not mismatches else "different_or_missing_content",
        "mismatches": mismatches,
        "observed_sha256": observed,
    }


def doctor(config: dict, *, archive: Path = ARCHIVE) -> dict:
    checked = archive_check(archive)
    required = [
        config["experiment"] / "engine-training-pairs.jsonl",
        config["snapshot"],
        config["places"],
    ]
    missing = [str(path) for path in required if not path.is_file()]
    result = {
        "check": "FAIL" if missing else "PASS",
        **checked,
        "missing": missing,
        "data_root": str(config["data_root"]),
        "offline_only": True,
        "live_matching_changed": False,
        "profiles": list(PROFILES),
    }
    if not missing:
        with sqlite3.connect(
            f"file:{config['snapshot'].as_posix()}?mode=ro&immutable=1", uri=True
        ) as database:
            database.execute("PRAGMA query_only=ON")
            if (
                database.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='event'"
                ).fetchone()
                is None
            ):
                raise ValueError("Snapshot has no event table")
        if not isinstance(json.loads(config["places"].read_text()), list):
            raise ValueError("Place catalogue must be a JSON list")
    return result


def relocate(text: str, config: dict, run: Path) -> str:
    replacements = {
        "/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite": str(config["snapshot"]),
        "/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json": str(config["places"]),
        "/tmp/vv-owner-corpus-2026-10-28/unit-guarded": str(config["snapshot"].parent),
        "/tmp/vv-five-group-recovery-2026-10-29": str(run),
        "/home/maan3/vv/VV-git": str(PROJECT),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if "/tmp/vv-" in text or "/mnt/c/Users/maan3" in text:
        raise ValueError("Unmapped historical path in executable staging source")
    return text


def offline_environment(run: Path) -> dict[str, str]:
    environment = os.environ.copy()
    # Use only repository test dummies, never the developer's service credentials.
    for line in (PROJECT / "backend/tests/evaluation/offline.env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            environment[key] = value
    environment["PYTHONPATH"] = os.pathsep.join((str(run), str(run / "frozen_backend")))
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.pop("PYTEST_ADDOPTS", None)
    return environment


def refresh_manifests(run: Path, config: dict, *, full: bool, reuse_index: bool = False) -> None:
    dependencies = {
        str(path.relative_to(run)): sha(path)
        for folder in ("frozen_backend", "frozen_analytics")
        for path in sorted((run / folder).rglob("*.py"))
    }
    manifest = {
        "files": dependencies,
        "aliases_sha256": sha(run / "aliases.py"),
        "geography_local_transitive_modules": [],
        "geography_data_files": [],
        "staged_replay": True,
    }
    write_json(run / "alias-dependency-manifest.json", manifest)
    write_json(
        run / "frozen-code-hashes.json",
        {
            "backend/" + key.removeprefix("frozen_backend/"): value
            for key, value in dependencies.items()
            if key.startswith("frozen_backend/")
        },
    )
    declaration = run / "engine-safety-declaration.json"
    if declaration.exists():
        value = json.loads(declaration.read_text())
        value.update(
            safety_code_sha256=sha(run / "engine-safety-declared.py"),
            main_engine_sha256=sha(run / "engine.py"),
            staged_replay=True,
        )
        write_json(declaration, value)
    if not full:
        return
    index = run / "community-index.sqlite"
    if index.exists() and reuse_index:
        module = ast.parse((run / "community_fingerprint.py").read_text())
        rules = next(
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "RULES" for target in node.targets
            )
        )
        updates = {
            "snapshot_path": str(config["snapshot"]),
            "snapshot_size": str(config["snapshot"].stat().st_size),
            "snapshot_mtime": str(config["snapshot"].stat().st_mtime_ns),
            "rules": hashlib.sha256(
                json.dumps(rules, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "code": sha(run / "community_fingerprint.py"),
            "places": sha(config["places"]),
        }
        with sqlite3.connect(index) as database:
            database.executemany(
                "UPDATE metadata SET value=? WHERE key=?", [(v, k) for k, v in updates.items()]
            )
        write_json(run / "stage-index-metadata.json", updates)
    # A downstream freeze includes upstream summaries (including elapsed time).
    # Leave every profile undeclared until its own first replay, after upstream
    # outputs have been regenerated. Dependency manifests above remain pinned.
    for pattern in ("community*frozen-rules.json", "community*input-manifest.json"):
        for path in run.glob(pattern):
            path.unlink()


def stage(
    config: dict, destination: Path, *, lightweight: bool = False, archive: Path = ARCHIVE
) -> dict:
    run = resolve_path(destination)
    if run.exists():
        raise ValueError("Run directory already exists; choose a fresh directory")
    protected = (
        config["experiment"],
        config["snapshot"].parent,
        archive.resolve(),
        PACKAGE.resolve(),
    )
    if run == config["data_root"] or any(run.is_relative_to(path) for path in protected):
        raise ValueError(
            "Run directory must not overwrite or sit inside cached baseline/code directories"
        )
    result = doctor(config, archive=archive)
    if result["check"] != "PASS":
        raise ValueError("Missing private inputs: " + ", ".join(result["missing"]))
    identity = (
        index_identity(config, archive)
        if not lightweight
        else {
            "reusable": False,
            "reason": "lightweight_stage_has_no_index",
        }
    )
    run.mkdir(parents=True, mode=0o700)
    inherited = []
    for source in sorted(config["experiment"].rglob("*")):
        if (
            not source.is_file()
            or "__pycache__" in source.parts
            or source.suffix in {".py", ".pyc", ".log"}
        ):
            continue
        relative = source.relative_to(config["experiment"])
        if relative.parts[0] in {"frozen_backend", "frozen_analytics"}:
            continue
        if lightweight and str(relative) not in LIGHT_INPUTS:
            continue
        if not lightweight and not identity["reusable"] and str(relative) not in REBUILD_INPUTS:
            continue
        target = run / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)  # Separate inode: replay cannot overwrite cached results.
        inherited.append(str(relative))
    runtime = {}
    for source in sorted((archive / "scripts").rglob("*.py")):
        relative = source.relative_to(archive / "scripts")
        if len(relative.parts) == 1 and source.name in HISTORICAL_ONLY:
            continue
        target = run / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(relocate(source.read_text(), config, run))
        runtime[str(relative)] = {"archive_sha256": sha(source), "staged_sha256": sha(target)}
    for folder in ("frozen_backend", "frozen_analytics"):
        shutil.copytree(archive / folder, run / folder)
    shutil.copyfile(PACKAGE / "namespace_delivery.py", run / "namespace_delivery.py")
    refresh_manifests(run, config, full=not lightweight, reuse_index=identity["reusable"])
    manifest = {
        "version": 1,
        "run_dir": str(run),
        "data_root": str(config["data_root"]),
        "snapshot": str(config["snapshot"]),
        "places": str(config["places"]),
        "lightweight": lightweight,
        "historical_outcomes_are_not_new_blind_validation": True,
        "baseline_overwritten": False,
        "runtime_sources": runtime,
        "inherited_data_files": inherited,
        "path_relocation_only": True,
        "cached_index_identity": identity,
        "index_rebuild_required_at_stage": not lightweight and not identity["reusable"],
    }
    write_json(run / "stage-manifest.json", manifest)
    return {
        "check": "PASS",
        "run_dir": str(run),
        "lightweight": lightweight,
        "staged_sources": len(runtime),
        "inherited_files": len(inherited),
    }


def require_run(path: Path) -> Path:
    run = resolve_path(path)
    if not (run / "stage-manifest.json").is_file():
        raise ValueError("Use stage to create an isolated run directory first")
    manifest = json.loads((run / "stage-manifest.json").read_text())
    if "cached_index_identity" not in manifest:
        raise ValueError("Stage predates content-identity checks; create a fresh run directory")
    return run


def execute(run: Path, profile: str) -> None:
    run = require_run(run)
    if profile not in PROFILES:
        raise ValueError("Unknown offline profile")
    if profile in INDEX_PROFILES and not (run / "community-index.sqlite").is_file():
        raise ValueError(
            "Replay community first: the cached index was not content-identical and must be rebuilt"
        )
    if profile in {"safety", "audit"} and not (run / "main-replayed.json").exists():
        raise ValueError("Replay main first: inherited metrics retain historical code fingerprints")
    if profile == "safety":
        inherited = run / "inherited-evidence"
        inherited.mkdir(exist_ok=True)
        for name in (
            "engine-raw-results.jsonl",
            "engine-raw-metrics.json",
            "engine-raw-holdout.jsonl",
        ):
            source = run / name
            if source.exists():
                shutil.move(source, inherited / name)
    subprocess.run(
        [sys.executable, str(run / PROFILES[profile])],
        cwd=run,
        env=offline_environment(run),
        check=True,
    )
    if profile == "main":
        write_json(
            run / "main-replayed.json", {"check": "PASS", "engine_sha256": sha(run / "engine.py")}
        )


def test(run: Path) -> None:
    run = require_run(run)
    scripts = sorted(run.glob("*-tests.py"))
    if not scripts:
        raise ValueError("No archived matching tests staged")
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--confcutdir", str(run), *map(str, scripts)],
        cwd=run,
        env=offline_environment(run),
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "stage"):
        command = commands.add_parser(name)
        command.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
        command.add_argument("--snapshot", type=Path)
        command.add_argument("--places", type=Path)
        if name == "stage":
            command.add_argument("--run-dir", type=Path, required=True)
            command.add_argument("--lightweight", action="store_true")
    command = commands.add_parser("test")
    command.add_argument("--run-dir", type=Path, required=True)
    command = commands.add_parser("replay")
    command.add_argument("profile", choices=PROFILES)
    command.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"doctor", "stage"}:
            config = paths(args.data_root, args.snapshot, args.places)
            result = (
                doctor(config)
                if args.command == "doctor"
                else stage(config, args.run_dir, lightweight=args.lightweight)
            )
            print(json.dumps(result, sort_keys=True))
            return 0 if result["check"] == "PASS" else 1
        if args.command == "test":
            test(args.run_dir)
        else:
            execute(args.run_dir, args.profile)
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, sqlite3.Error) as error:
        print(f"owner-recovery: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
