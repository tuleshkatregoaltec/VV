"""Positive controls prove indexed retrieval retains previously accepted full namespaces."""
import importlib.util,json,sqlite3
from pathlib import Path
P=Path(__file__).parent;spec=importlib.util.spec_from_file_location('namespace',P/'engine-namespace-all.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=sqlite3.connect('file:/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite?mode=ro&immutable=1',uri=True);c.execute('PRAGMA query_only=ON');n=0;recovered=0;proved=0
for line in (P/'engine-training-pairs.jsonl').open():
 r=json.loads(line);s,_=m.normalize_context(r['source']);raw=s.get('original_identifiers',{});code=m.e.tm.identifier(str(raw.get('building_number') or ''));parsed=m.parse_r3(code)
 if not parsed:continue
 amount=m.e.tm.positive_decimal(s['amount_aed']);rows=[json.loads(p[0]) for p in c.execute("SELECT e.payload FROM property_lookup p JOIN event e ON e.rowid=p.event_rowid WHERE (p.identifier=? OR p.villa_number=?) AND e.family='sale' AND e.amount BETWEEN ? AND ?",(code,parsed[1],float(amount)-2,float(amount)+2))];n+=1;recovered+=any(t['event_key']==r['target']['event_key'] for t in rows);proved+=any(t['event_key']==r['target']['event_key'] and m.source_namespace(s,t) for t in rows)
 if n==20:break
assert n==20 and recovered==20 and proved==20 and c.total_changes==0
summary={'check':'PASS','known_accepted_namespace_pairs':n,'expected_events_retrieved':recovered,'full_namespace_proven':proved,'sqlite_total_changes':c.total_changes};(P/'engine-namespace-positive-control.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
