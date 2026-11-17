# Owner import: five-group recovery handoff

This is the entry point for Claude, Kimi, or another agent continuing the **29 October 2026 offline experiment**. Read `AGENTS.md` and `development.md` first.

## What is actually implemented?

| Layer | Status | Location |
|---|---|---|
| Existing owner importer and owner-history logic | Implemented in the application. Its current resolver identifier is `owner-qualified-17`; the matching-policy module also has its own `owner-qualified-1` version. These are different version fields. | `backend/app/crm/ownership.py`, `owner_matching_policy.py`, `owner_namespaces.py`, `owner_history.py`, `owner_assessment.py`, `import_events.py`, `transaction_matching.py` |
| Five-group experiment, alias learning, C1–C5, namespace probe, tests | Implemented as **offline research scripts**, preserved in the project with their historical frozen dependencies. | `backend/scripts/crm/owner_recovery_experiment/` |
| Durable inputs and original workbooks | Available locally; deliberately Git-ignored. They do not accompany a normal Git clone. | `.local/owner-recovery/2026-10-29/` |
| Unresolved-only Excel exporter | Implemented, tested, and runnable against the frozen final ledger. | `backend/scripts/crm/export_unresolved_owner_rows.py` |
| Automatic acceptance of the 2,776 experimental proposals | **Not integrated into the live importer.** No owner claims, current/former-owner assignments, notes, or workspaces were updated by the experiment. | Not a production feature |

“Coded” does not mean “proven correct” or “deployed.” The experimental scripts reproduce explicit assumptions and candidate decisions. They are not a trained ownership-truth model. Historical code is deliberately preserved rather than silently rewritten to look like production code; see the package README for staging and replay commands.

## User objective and boundaries

Company spreadsheets contain owner/contact names and property/transaction clues. The intended product links those records to the correct DXBI property and transaction, then supports owner-history displays. Property identity, transaction identity, and current-owner status are three different claims.

The latest experiment targeted **only five fixed issue buckets**. Keep the other rows and existing assignments unchanged when comparing improvements. Use DXBI only; the user explicitly excluded a separate DLD dataset. Do not invent an identifier or choose an arbitrary same-price property just to raise a match percentage. Preserve original values and record inferred/normalised values separately.

The user permitted broad, explicit assumptions, with these numeric rules:

- Sale amount difference at most **AED 2**, evaluated with decimal arithmetic.
- Size tolerance **max(50 square feet, 2% of source size)** after establishing or explicitly hypothesising the source unit.
- Supplied child identifiers must agree through a supported full identifier/namespace. A missing identifier can be proposed from sufficiently discriminating evidence; a conflicting supplied identifier cannot silently become “missing.”
- Date differences can be proposed with visible warnings. They do not establish that a contact belongs to the inferred transaction or is the current owner.

No owner/contact records were sent to an external LLM by this experiment. The new unresolved workbook includes the original private owner/contact columns for local inspection.

## Frozen scope and reconciled result

| Original issue | Starting rows | Additional candidates | Already matched before experiment | Remaining |
|---|---:|---:|---:|---:|
| No usable original unit/villa/plot identifier | 13,563 | 2,601 | 0 | 10,962 |
| Location label not recognised in captured catalogue | 7,844 | 0 | 0 | 7,844 |
| Property found, but no sale within ±2 AED | 6,053 | 4 | 8 | 6,041 |
| Conflicting address identifiers | 5,341 | 0 | 0 | 5,341 |
| Same-price scoped sales, but identifier differs | 3,301 | 171 | 0 | 3,130 |
| **Total** | **36,102** | **2,776** | **8** | **33,318** |

The 36,102 rows represent 23,545 source events. The 2,776 proposals point to 1,091 distinct DXBI sale events and 1,024 properties; these are not counts of verified owners or newly created properties. The unresolved set includes **31,615 extreme rejected suggestions + 1,288 tentative rejected suggestions + 415 rows without a selected candidate**. A non-null `selected` field does not mean the row matched.

The source population was nine comparable workbooks: 110,866 raw rows = 110,327 named rows + 539 nameless rows. The other 74,225 named rows were outside these five buckets. A row may have several defects, but its original bucket remains fixed throughout this experiment.

## What each profile does

The implementation, frozen rule declarations, and tests are authoritative. The table describes their intent and incremental contribution after union/deduplication.

| Profile | Rule and assumptions | Additional rows |
|---|---|---:|
| Conservative main | Complete global ±2 sale pool; qualified building/parent scope; original role-correct ID or cautious missing-ID inference; independent size/exact-date corroboration; conflict/reuse vetoes. Generic tower names need independent context. | 0 |
| C1 | Explicit narrow community + price + exact day + independently interpreted size + recognised compatible physical type; unique property/event; nearby/undated competitor veto. | 0 |
| C2 | C1, but try both sqft and sqm for otherwise unlearnable units; uniqueness and competitor checks operate on the union of hypotheses. Candidate-dependent size units are flagged. | 0 |
| C3 | C2, with broad labels `Residential`, `Building`, `Unit` supplying no reliable physical-form discriminator. Preserve numbered building constraints and specific type conflicts. | 0 |
| C4 | C3 without a date selector, but require exactly one surviving sale event across the **entire** captured community/price/size history. | 4 |
| C5 exact | Demonstrated spreadsheet label-sequence repair, followed by C3. | 1,784 |
| C5 history | Same repair, followed by C4; count only gains beyond earlier profiles. | 817 |
| Full R3 namespace, exact date | Full raw R3 code + independently agreeing named cluster/project + agreeing numeric label + size + amount, using the existing production namespace grammar. | 158 |
| Full R3 namespace, date relaxed | Same identity proof, but dates differ. | 13 |
| **Total** | Union by original row key; all profiles checked together against existing accepted rows. | **2,776** |

The last five nonzero contributions are the delivered candidate tiers. They comprise **1,942 exact-date rows and 834 date-relaxed rows**. The maximum observed amount difference was AED 1, although the rule permits AED 2.

### Alias and measurement learning

- Building/parent aliases require at least three independent matched units and 100% destination purity. Query source/target support cannot justify its own alias. Parent plot codes may establish building context, not a child unit.
- Size-unit inference uses at least ten independent training properties and at least 95% exclusive votes per sheet, leaving out the recognised queried source unit. It does not infer sqm merely because an expensive property “cannot be that small.”
- `sqm × 10.7639104167` supplies sqft. Unknown measurement units otherwise abstain or enter the explicitly labelled C2 hypothesis branch.
- All competing sales are considered; displayed alternatives can be truncated, candidate selection cannot.
- Rentals remain separate evidence. A matching rent amount is not a purchase/owner-transfer match. The frozen snapshot contains 993,778 sales and 1,684,777 rental events; it is not a guarantee that every real transaction is present.

### The substantial source defect: Damac labels

In `Damac hills 2 April 2024.xlsx`, Sheet1, rows **11,086–28,378** contain an exact arithmetic sequence: `DAMAC HILLS 3` through `DAMAC HILLS 17295`, with suffix = row number − 11,083. This strongly suggests accidental spreadsheet autofill; the adjacent valid label `DAMAC HILLS 2` is never overwritten.

Of these damaged-label rows, **13,815** lie in the five-group scope, including **13,244** in the missing-identifier bucket. Frozen training evidence supplies 1,480 distinct physical properties / 1,479 source units from the same sheet, all pointing to Damac Hills 2. C5 requires at least ten surviving independent properties and source units, 100% community purity, matching name prefix, query-source and candidate-property exclusion, and no conflicting valid community or precise location. Unknown-community training evidence cannot be silently dropped to manufacture purity.

Only the query copy is repaired. Original workbook values and all out-of-scope rows remain unchanged. A repaired location alone is not a recovered unit or transaction.

### Full code versus arbitrary suffix

`R3 Ruba-V-357` can identify Arabian Ranches 3 / Ruba / 357 only when the other original namespace evidence agrees. The probe recognises the known `III`, `lll`, and `3` master-project spelling variants. It does **not** equate every code ending in 357 with the same villa.

The user's `AFMU019B` example is already a complete DXBI plot code. Chopping it to “villa 19B” is unsupported. That particular source row is outside these five groups and was not counted as a gain.

All 5,341 original contradiction rows come from the Arabian Ranches 3 workbook. For example, one row supplies `R3 Sun-V-204` and `R3 Sun-V-201` in different address columns. No contradiction-cohort row was promoted by the namespace probe.

## Validation and important limits

- The main profile used 7,397 training pairs and 1,839 held-out pairs split by connected target-property/source-unit components. It selected 556 masked-ID holdout pairs, all agreeing with earlier accepted event/property labels. Those labels are weak references, not independently verified ground truth.
- C1/C2/C3/C4/C5 were replayed and adversarially tested. Later variants reused the holdout after earlier diagnostic outcomes; their agreement is not an independent accuracy estimate.
- **The repaired-label subset has zero repaired examples in that masked holdout.** The 589/589 exact-profile agreement must not be presented as measured C5 repair accuracy.
- The separate namespace rule has **no blind holdout accuracy estimate**. All 171 proposals were independently replayed against uncapped price pools; positive controls and constraint tests passed.
- The corrected history profile has **12 different-property disagreements** against earlier accepted labels. All involve source `Land` versus reference DXBI `Villa`. Treating those type labels as decisive can remove a legitimate rival. Investigating a uniform plot/villa treatment is a useful next experiment, but must retain rivals rather than force uniqueness.
- Initial candidate-search bugs were fixed before delivery: legal-area records such as Jabal Ali 1 / Al Furjan must remain in the community pool; and generic numbered buildings such as Tower 1 must retain their negative identifier constraints. Archived preflight runs are **not** final results.
- Date-relaxed rules have **no maximum date gap**. Actual maximum: **2,765 days**. Of 834 date-relaxed rows, 511 exceed one year, 471 exceed two years, and 258 exceed five years; these thresholds overlap. A later registration stage is a hypothesis, not proof of owner identity.
- Seven CRM tables were fingerprinted before/after and independently checked unchanged, including 217,743 claims. No live importer acceptance or owner-history migration occurred.

## Files and commands

Run from the repository root. The commands do not require a live database for offline analysis.

```bash
just owner-recovery --help
just owner-recovery doctor
just export-unresolved-owner-rows --output /absolute/path/Unresolved-33318-Rows.xlsx
just test-backend tests/unit/test_export_unresolved_owner_rows.py tests/unit/test_owner_recovery_handoff.py
```

See `backend/scripts/crm/owner_recovery_experiment/README.md` for exact fresh-stage, test and replay arguments. Full main replay is intentionally explicit because it evaluates millions of candidate pairs and previously took about 30 minutes. Use a fresh run directory, not the cached baseline, when changing rules.

Local evidence layout:

```text
.local/owner-recovery/2026-10-29/
  experiment/                  frozen baseline, inputs, results, audit evidence
    rows.jsonl                 exactly 36,102 property-only focus rows
    baseline-matched.jsonl     44,414 existing accepted sale references
    all-rows.jsonl             110,327 named source rows, property evidence only
    engine-training-pairs.jsonl
    final-row-results.jsonl.gz delivered row-by-row decisions and diagnostics
  dxbi/
    snapshot.sqlite            read-only captured DXBI events
    places-snapshot.json       read-only catalogue
  sources/                     nine original private source workbooks
  source-workbooks.json        workbook hashes
  parser-mappings.json         original header rows and column mappings
  source-manifest.json         original sampling inventory
```

All `.local/owner-recovery/` content is Git-ignored and private. There are no credentials in the handoff. The tracked historical code and docs are available in the working tree; no commit/push is implied. A different computer needs an authorised copy of the local evidence, not just a clone.

Output directory on this machine:

`/mnt/c/Users/maan3/Downloads/owner-import-five-group-experiment-2026-10-29/`

- `Unresolved-33318-Rows.xlsx`: unresolved-only diagnostic ledger plus source tabs with every original column. Source tabs repeat the ledger rows; do not add both views together.
- `Unresolved-33318-Rows.audit.json`: counts, source reconciliation and output checksum.
- `Five-Group-Recovery-Experiment.xlsx`: prior full 36,102-row experiment with rules and examples.
- `Read-Me-Examples.html`: readable explanation, including the most extreme proposed link.
- `Audit/row-results.jsonl.gz`: full delivered property-only audit.

## Changing rules without corrupting the baseline

Keep the fingerprinted archive and cached baseline intact. Start a new staged run, then implement a separately versioned experimental profile with new output filenames and tests. The historical freeze assertions intentionally reject silently changing a previously declared profile. Record new rule/code/input fingerprints and compare against the fixed row keys; do not delete guards merely to make an old benchmark appear to pass. The archive reproduces past work, while the staged directory is the workspace for new hypotheses.

## Suggested next investigation

1. Start with the **33,318 remaining row keys**, not every row that has a candidate. `tentative` and `tentative_high_risk` remain unresolved even when `selected` is populated.
2. Audit why 9,331 remaining missing-ID rows have multiple same-price/size history events after location repair. For the exact-date view, 523 repaired missing-ID rows have multiple exact-day candidates and 821 are vetoed by nearby/undated competitors. These are overlapping alternative views, not additive new issue buckets.
3. Examine complete original cadastral fields and complete DXBI payloads for independent identifiers before loosening price, size, location or collision checks. Original source tabs now expose all columns. Do not truncate full codes speculatively.
4. Investigate structured Emirates/Springs address roles and plot-versus-villa metadata with a train/evaluation split. Existing R3 parsing is not evidence that arbitrary Emirates suffixes are safe.
5. Keep strong candidates, weaker assumptions, and unresolved conflicts separate. Evaluate newly introduced rules on independent labelled cases; preserve all original values and report counterexamples.
6. If integrating a validated rule later, use the existing domain layers and tenant-scoped import/history flow. Production acceptance, persistence, current/former-owner projection, failure handling and API/UI contract tests are separate work from this offline archive.

## Prompt to give another agent

> Read `docs/crm-owner-recovery-handoff.md` and the offline package README. Run the doctor and targeted tests. Continue the five-group experiment using the durable local cache and the unresolved-only workbook. Seek additional defensible DXBI property/transaction links, keep the ±2 AED and max(50 sqft, 2%) rules, preserve original identifiers and out-of-scope assignments, and record every new assumption with original-row versus target examples. Prioritise independent cadastral/namespace evidence and investigate the Land/Villa and duplicate-candidate failures. Do not interpret candidate counts or weak-label agreement as verified ownership accuracy. Report reconciled row/property/transaction counts and counterexamples. Keep experimental proposals separate from live importer acceptance.
