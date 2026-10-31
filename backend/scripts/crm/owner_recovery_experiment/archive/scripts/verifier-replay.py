"""Independently reconstruct train-only models and replay actual supported outcomes."""
import collections,json,sys,time,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));import engine as e
from aliases import AliasModel

def read(name):return [json.loads(l) for l in (ROOT/name).open()]
def main():
 started=time.time();metrics=json.loads((ROOT/'metrics.json').read_text())
 if metrics.get('safety_filter'):
  spec=importlib.util.spec_from_file_location('verifier_safety',ROOT/'engine-safety.py');safety=importlib.util.module_from_spec(spec);spec.loader.exec_module(safety);e.factor=safety.guarded_factor
 train=read('engine-training-pairs.jsonl');focus={r['row_key']:r for r in read('rows.jsonl')};results=read('results.jsonl');hold=read('engine-holdout.jsonl')
 model=AliasModel(baseline_pairs=[{'source':{**p['source'],'source_event_id':p['source_event_id'],'source_unit_id':p['source_unit_id'],'raw_fields':p.get('raw_fields',{})},'target':p['target']} for p in train],places=json.loads(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json').read_text()))
 sizes=e.SheetSizeEvidence()
 for p in train:sizes.observe(p['source'],[(p['target'],200,[])])
 pools=e.Pools('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite');groups=collections.defaultdict(list)
 for r in sorted(results,key=lambda r:r['row_key']):
  if r['status']=='new_supported_inferred':groups[(r['primary_cause'],r['rule'])].append(r)
 checks=[];seen=set()
 for key,rs in groups.items():
  for r in rs:
   if len([v for v in checks if (v['cause'],v['rule'])==key])>=5:break
   uid=(r['source_event_id'],e.digest(r['source']))
   if uid in seen:continue
   seen.add(uid);original=focus[r['row_key']];pool,rent=pools.get(original['source']['amount_aed']);actual=e.select(original,pool,rent,model,sizes)
   checks.append({'row_key':r['row_key'],'cause':key[0],'rule':key[1],'pool_size':len(pool),'same_selected_event':actual['selected']['event_key']==r['selected']['event_key'],'same_status':actual['status']==r['status']})
 baseline={r['source_event_id']:r for r in read('baseline-matched.jsonl')};hchecks=[]
 for r in sorted(hold,key=lambda r:r['source_event_id']):
  if r['status']!='new_supported_inferred':continue
  original=baseline[r['source_event_id']];pool,rent=pools.get(original['source']['amount_aed']);actual=e.select(original,pool,rent,model,sizes,mask=True)
  hchecks.append({'source_event_id':r['source_event_id'],'pool_size':len(pool),'same_selected_event':actual['selected']['event_key']==r['selected']['event_key'],'same_status':actual['status']==r['status']})
  if len(hchecks)>=20:break
 ok=all(c['same_selected_event'] and c['same_status'] for c in checks+hchecks)
 out={'check':'PASS' if ok else 'GAPS','focus_supported_replays':checks,'holdout_supported_replays':hchecks,'sqlite_total_changes':pools.db.total_changes,'elapsed_seconds':round(time.time()-started)}
 (ROOT/'verifier-replay.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps({'check':out['check'],'focus_replayed':len(checks),'holdout_replayed':len(hchecks),'sqlite_total_changes':pools.db.total_changes,'elapsed_seconds':out['elapsed_seconds']}))
if __name__=='__main__':main()
