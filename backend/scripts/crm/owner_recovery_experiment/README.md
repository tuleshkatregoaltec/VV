# Offline owner recovery experiment (2026-10-29)

This package archives the finished five-group investigation. It does **not** change
`app/crm` matching, API behavior, assignments, contacts, or any production database.
The archived Python sources are searchable and byte-for-byte fingerprinted in
`archive/manifest.json`, including the frozen backend/geography used historically.
Hyphenated historical filenames are intentional.

Private data is excluded from tracked code. The default local cache is:

```
.local/owner-recovery/2026-10-29/
  experiment/                    # original workspace/evidence; never execute here
    rows.jsonl                   # fixed 36,102-row cohort
    baseline-matched.jsonl
    all-rows.jsonl
    engine-training-pairs.jsonl
    community-index.sqlite
    final-row-results.jsonl.gz
    ...                          # profiles, declarations, reports and source provenance
  dxbi/
    snapshot.sqlite              # immutable DXBI event snapshot
    places-snapshot.json
```

Use the repository Python environment through `just owner-recovery` (or, from
`backend`, `uv run python -m scripts.crm.owner_recovery_experiment.cli`). No live
service setup is needed. Subprocesses receive the repository's test-only dummy
configuration, disabled telemetry and local port-9 endpoints.

## Quick verification

From the repository root, choose a new directory for every staged run:

```sh
just owner-recovery doctor
just owner-recovery stage --lightweight --run-dir .local/owner-recovery/2026-10-29/runs/proof-01
just owner-recovery test --run-dir .local/owner-recovery/2026-10-29/runs/proof-01
just owner-recovery replay proof --run-dir .local/owner-recovery/2026-10-29/runs/proof-01
```

The lightweight stage copies only training pairs and code. Archived matching tests
exercise the original guards; `proof` retrieves 20 real previously accepted events
from the configured immutable snapshot and checks their complete R3 namespace.
This is a retrieval/control check, not ownership-accuracy validation.

All relative CLI paths resolve against the repository root, including when the
`just` recipe runs Python from `backend`. Override
`--data-root`, `--snapshot` and `--places` on `doctor`/`stage` for another machine.
Absolute paths are also accepted.

## Full replay

Omit `--lightweight` to copy the cached evidence into an isolated writable run:

```sh
just owner-recovery stage --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay namespace --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay namespace-delivery --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay community --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay c2 --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay c3 --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay c4 --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay c5 --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay community-combine --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
just owner-recovery replay combine --run-dir .local/owner-recovery/2026-10-29/runs/replay-01
```

`community-combine.py` preserves C1–C5 precedence, disagreements and global vetoes.
`combine_profiles.py` then prefers exact-date namespace proposals, community
proposals, and finally date-relaxed namespace proposals; it rejects target
conflicts and reruns cross-profile reuse/source-property vetoes. The previously
inline namespace-delivery derivation is now `namespace_delivery.py`.

Optional profiles: `roles`, and the expensive `main` → `safety` → `audit` sequence.
The original complete-pool `main` run took about 30 minutes; it is never run by
`doctor`, `stage`, `test` or `proof`. `safety`/`audit` require a freshly replayed main
because inherited metrics keep their historical code fingerprints.

Staging refuses existing directories and cache/code destinations. It copies data
with independent inodes, rewrites only historical path literals in executable
copies, refreshes dependency manifests, and removes inherited community declarations.
Each community profile freezes its current inputs on its first actual replay, after
upstream summaries have been regenerated. Staging never pre-freezes C1–C5 against
inherited summaries. Replay the chain once in order in a fresh stage; changing an
upstream result after a downstream profile is frozen requires a fresh stage.
It reuses the copied community index only
when SHA256 hashes of the configured snapshot, catalogue **and cached index** match
the tracked historical `archive/input-identity.json`; a different path with identical
content is fine. Only then may metadata in the **copied** index be repointed.

If content differs or identity cannot be proved, staging excludes the old index
and derived profile results. Run `replay community` first to rebuild the index and
C1 result from the configured data, then replay C2–C5 in order before combining.
Downstream index profiles fail until that rebuild exists. Source cohorts and weak
labels must themselves be compatible with a replacement snapshot; missing reference
events fail loudly. Old stage directories created before this identity check must
be staged again. The snapshot and original cache remain untouched.
`stage-manifest.json` records original/staged hashes and inherited files. Replays
are historical reproductions with outcomes already visible, not new blind tests.

## Reading the logic and limitations

Start with `archive/scripts/engine.py`, `aliases.py`, `community_fingerprint.py`,
`community-c2.py` through `community-c5.py`, `engine-namespace-all.py`,
`community-combine.py`, and `combine_profiles.py`. Tests remain beside these
historical scripts. Reports/reasoning are preserved in `report.py`,
`explanation.py`, verifier scripts and cached JSON evidence. The cache also retains
superseded retrieval/building diagnostics; they are provenance, not final results.

Source-export/live-read scripts (`prepare.py`, `check_database.py`) and historical
machine-specific packaging/price-audit helpers are archived for inspection only.
They are excluded from executable staging or the CLI allowlist. The wrapper never
refreshes PostgreSQL exports or invokes live evaluation models.

The conservative profile found zero new recoveries and eight already-live rows.
Additional profiles are conditional proposals. Date-relaxed events remain visibly
separate, including very large date gaps; price tolerance remains ±2 AED. Previously
accepted pairs are weak labels, not owner truth. The original masked holdout score
does not validate later exploratory profiles or establish ownership accuracy.
