"""Replay date-free holdout collisions using full raw snapshot price pools."""
import json,collections,sys,importlib.util,sqlite3,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));import engine as e;import community_fingerprint as c1
spec=importlib.util.spec_from_file_location('verifier_c4_profile',ROOT/'community-c4.py');c4=importlib.util.module_from_spec(spec);spec.loader.exec_module(c4)
def read(name):return [json.loads(l) for l in (ROOT/name).open()]
train=read('engine-training-pairs.jsonl');hold=read('community-c4-holdout.jsonl');focus=read('community-c4-results.jsonl');summary=json.loads((ROOT/'community-c4-summary.json').read_text());baseline={r['source_event_id']:r for r in read('baseline-matched.jsonl')};places=json.loads(c1.PLACES.read_text());communities=c1.Communities(places);sizes=e.SheetSizeEvidence();aliases=c1.AliasModel([{'source':{**p['source'],'source_event_id':p['source_event_id'],'source_unit_id':p['source_unit_id'],'raw_fields':p['raw_fields']},'target':p['target']} for p in train],places=places)
for p in train:sizes.observe(p['source'],[(p['target'],200,[])])
pools=e.Pools(c1.SNAPSHOT)
def reference_history(index,community,amount):return [t for t in pools.get(amount)[0] if communities.target(t)==community]
c4.history=reference_history
selected=[r for r in hold if r['status']==c4.STATUS];collisions=[r for r in selected if r['selected']['property']!=r['weak_property']];agree=[r for r in selected if r['selected']['property']==r['weak_property']];assert len(collisions)==7 and len(selected)==371
checks=[]
for r in collisions+agree[:13]:
 original=baseline[r['source_event_id']];actual=c4.select(c1.masked_row(original),None,communities,aliases,sizes);assert actual['status']==r['status'] and actual['selected']['event_key']==r['selected']['event_key'];checks.append({'source_event_id':r['source_event_id'],'weak_property':r['weak_property'],'selected_property':r['selected']['property'],'weak_event':r['weak_event'],'selected_event':r['selected']['event_key'],'source_amount':original['source']['amount_aed'],'source_raw_size':original['source'].get('size_unknown'),'selected_size':r['selected']['target'].get('size_sqft'),'selected_date_gap':r.get('date_evidence',{}).get('gap_days'),'different_property':r in collisions,'raw_snapshot_replay_pass':True})
assert collections.Counter(r['status'] for r in focus)==summary['statuses']
for name,sha in json.loads((ROOT/'community-c4-input-manifest.json').read_text()).items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==sha,name
report={'check':'PASS','selected_holdout':len(selected),'same_property':len(agree),'different_property_weak_label_disagreements':len(collisions),'raw_snapshot_replays':len(checks),'checks':checks,'new_focus_candidates':sum(r['status']==c4.STATUS for r in focus),'sqlite_total_changes':pools.db.total_changes,'limitation':'Reused weak labels are not truth or precision; seven different-property disagreements remain explicit.'};(ROOT/'verifier-c4.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='checks'}))
