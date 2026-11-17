"""Verify all conditional profile union keys, target agreement, and global reuse."""
import json,sys,collections,sqlite3
from pathlib import Path
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P));import engine as e

def records(name):
 for l in (P/name).open():yield json.loads(l)
focus={r['row_key']:r for r in records('rows.jsonl')};options=collections.defaultdict(list);counts={}
for profile,name in [('C1','community-results.jsonl'),('C2','community-c2-results.jsonl'),('C3','community-c3-results.jsonl'),('C4','community-c4-results.jsonl'),('C5exact','community-c5-exact-results.jsonl'),('C5history','community-c5-history-results.jsonl')]:
 keys=set();n=0
 for r in records(name):
  assert r['row_key'] not in keys;keys.add(r['row_key'])
  if str(r['status']).startswith('conditional'):
   options[r['row_key']].append((profile,r));n+=1
 assert keys==set(focus);counts[profile]=n
for r in records('engine-namespace-delivery.jsonl'):options[r['row_key']].append(('namespace',r))
conflicts={k:[(p,r['selected']['event_key'],r['selected']['property']) for p,r in rs] for k,rs in options.items() if len({(r['selected']['event_key'],tuple(r['selected']['property'])) for p,r in rs})>1};assert not conflicts
combined={r['row_key']:r for r in records('combined-conditional-results.jsonl')};assert set(combined)==set(focus)
positive={k:r for k,r in combined.items() if r['status']=='conditional_rule_c_candidate'};assert set(positive)==set(options)
for key,r in positive.items():assert (r['selected']['event_key'],tuple(r['selected']['property'])) in {(x['selected']['event_key'],tuple(x['selected']['property'])) for p,x in options[key]}
base=list(records('baseline-matched.jsonl'));db=sqlite3.connect('file:'+str(P/'community-index.sqlite')+'?mode=ro&immutable=1',uri=True);targets={k:json.loads(v) for k,v in db.execute('select event_key,payload from baseline_target')};refs=[(r,targets[e.current_key(r)]) for r in base];tmp=[(focus[k],{**r,'status':'new_supported_inferred'}) for k,r in positive.items()];veto=e.veto(tmp,[],refs);assert all(r['status']=='new_supported_inferred' for original,r in tmp)
summary=json.loads((P/'combined-conditional-summary.json').read_text());assert dict(collections.Counter(r['status'] for r in combined.values()))==summary['statuses']
out={'check':'PASS','focus_rows':len(focus),'conditional_union_rows':len(positive),'profile_raw_positive_rows':counts,'same_row_different_target_conflicts':len(conflicts),'independent_global_reuse_demotions':0,'known_baseline_reference_rows':len(refs),'distinct_source_events':len({focus[k]['source_event_id'] for k in positive}),'distinct_dxbi_events':len({r['selected']['event_key'] for r in positive.values()}),'distinct_dxbi_properties':len({tuple(r['selected']['property']) for r in positive.values()}),'global_veto_diagnostic':veto};(P/'verifier-union.json').write_text(json.dumps(out,sort_keys=True,indent=2)+'\n');print(json.dumps(out,sort_keys=True))
