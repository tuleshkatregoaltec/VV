import gzip,hashlib,json,shutil
from pathlib import Path
R=Path(__file__).parent;O=Path('/mnt/c/Users/maan3/Downloads/owner-import-five-group-experiment-2026-10-29');A=O/'Audit';A.mkdir(exist_ok=True)
names=['baseline-summary.json','combined-conditional-summary.json','community-combined-summary.json','community-c5-repair-evidence.json','label-sequence-evidence.json','price-boundary-summary.json','validation-report.json','database-unchanged-check.json','metrics.json','engine-frozen-rules.json','engine-namespace-all-rule.json','engine-namespace-delivery-summary.json','community-frozen-rules.json','community-c2-frozen-rules.json','community-c3-frozen-rules.json','community-c4-frozen-rules.json','community-c5-frozen-rules.json','alias-learned-crosswalk.json','alias-dependency-manifest.json','frozen-code-hashes.json','verifier-invariants.json','verifier-namespace.json','verifier-c5-final.json','verifier-c4-final.json','verifier-union.json','verifier-deliverable.json','verifier-database.json','verifier-label-sequence.json']
for name in names:
 p=R/name
 if p.exists():shutil.copy2(p,A/name)
C=A/'experiment-code';C.mkdir(exist_ok=True)
for name in ['engine.py','aliases.py','community_fingerprint.py','community-c2.py','community-c3.py','community-c4.py','community-c5.py','community-combine.py','engine-namespace-all.py','combine_profiles.py','label_sequence.py','price_boundary.py','report.py','explanation.py','validation_report.py']:
 p=R/name
 if p.exists():shutil.copy2(p,C/name)
(O/'START-HERE.txt').write_text('FIVE-GROUP OWNER-IMPORT EXPERIMENT\n\nOpen Read-Me-Examples.html for the explanation.\nOpen Five-Group-Recovery-Experiment.xlsx for filters and the full row ledger.\n\n36,102 original rows = 8 already matched + 2,776 additional conditional candidates + 33,318 still unresolved.\nThe 2,776 candidates include 1,942 exact-date rows and 834 date-relaxed rows.\nThey point to 1,091 DXBI sale events and 1,024 properties; these are not counts of verified owners.\n\nThe original five buckets remain fixed. No live import, claim, note or workspace was changed.\n\nWorkbook tabs: Summary; Rules; All 36102 rows; Examples; Counting units; Rejected price examples; Remaining reasons; Conditional assumptions; By file; Validation; Validation disagreements.\nGreen = existing/conservative support. Blue = conditional assumptions. Yellow = date review on full-code namespace cases. Orange = date review plus other assumptions. Red = extreme suggestion, not accepted.\n\nAudit/ contains exact rules, reconciliation, validation, source-pattern evidence, code copies and the compressed full JSONL audit. Source owner names/contact details are intentionally excluded; original property fields and file/sheet/row references are retained.\n\nLimits: these are candidate links. The damaged-label subset has no direct masked-holdout accuracy result. The namespace profile has no blind holdout accuracy estimate. The history profile disagrees with earlier property links in 12 held-out cases, involving Land versus Villa. Earlier accepted links are weak references, not independent truth.\n')
(A/'REPRODUCIBILITY.txt').write_text('The final experiment workspace is /tmp/vv-five-group-recovery-2026-10-29. Code copies are provided here for inspection; relative inputs remain in that workspace.\nThe immutable DXBI SQLite snapshot is /tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite. Its complete sales and rental amount pools were inspected read-only.\nThe frozen backend source, training inputs and source exports remain in the private experiment workspace. They are required to rerun; code copies alone are not a standalone package. No credentials are included.\nThe repository virtual environment /home/maan3/vv/VV-git/backend/.venv/bin/python supplies the runtime.\nThe report is an offline proposal: no import/owner assignments were written.\n')
p=O/'row-results.jsonl';z=A/'row-results.jsonl.gz';h=hashlib.sha256()
with p.open('rb') as src,gzip.open(z,'wb',compresslevel=6) as dst:
 for b in iter(lambda:src.read(1024*1024),b''):h.update(b);dst.write(b)
check=hashlib.sha256()
with gzip.open(z,'rb') as src:
 for b in iter(lambda:src.read(1024*1024),b''):check.update(b)
assert h.hexdigest()==check.hexdigest()
uncompressed=p.stat().st_size;p.unlink()
manifest={}
for f in O.rglob('*'):
 if f.is_file():
  hash=hashlib.sha256()
  with f.open('rb') as src:
   for b in iter(lambda:src.read(1024*1024),b''):hash.update(b)
  manifest[str(f.relative_to(O))]={'bytes':f.stat().st_size,'sha256':hash.hexdigest()}
manifest['compressed_row_audit_verification']={'uncompressed_bytes':uncompressed,'uncompressed_sha256':h.hexdigest(),'verified_round_trip':True}
(O/'artifact-manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'packaged_files':len(manifest)-1,'compressed_audit_bytes':z.stat().st_size,'uncompressed_audit_bytes':uncompressed,'round_trip_verified':True}))
