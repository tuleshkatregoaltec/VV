"""Predeclared generic-building restriction; replay only, never relax a matcher rule."""
from __future__ import annotations
import collections, hashlib, importlib.util, json, shutil, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('five_group_engine',ROOT/'engine.py');engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
from aliases import AliasModel
from app.crm.owner_matching_policy import hierarchy_flags
SAFETY_RULE={'version':'generic-building-safety-1','declaration':'Frozen before reading any recovery or holdout outcomes.','restriction':'Generic/numeric source building requires an independent named project matching the target project, an established production hierarchy guard, or an independently accepted scoped parent alias. Broad area and a generic building alias alone are insufficient.','effect':'Replay affected raw focus and masked holdout frames with an added location veto, then rerun the same global conflict veto. No amount/size/date threshold changes.'}
def save(name,v):engine.save(name,v)
def source_building(s):return str(s.get('building_name') or '')
def generic(s):
 b=source_building(s);return bool(b and (engine.tm.generic_building(b) or engine.tm.identifier(b).isdigit()))
def independent_named_project(s,t):
 raw=s.get('raw_fields',{});locations=s.get('raw_location_fields',{})
 p=raw.get('project_name') if 'project_name' in raw else locations.get('project_name') if 'project_name' in locations else s.get('project_name')
 p=engine.tm._location(p);q=engine.tm._location(t.get('project_name'))
 if not p or not q or engine.tm.generic_building(p) or engine.tm.identifier(p).isdigit():return False
 if engine.tm.normalize_location(p,area=True)==engine.tm.normalize_location(s.get('area_name'),area=True):return False
 return engine.tm.property_scope_matches(p,q)
def proof(s,t,f):
 if independent_named_project(s,t):return 'independent_named_source_project_matches_target'
 if hierarchy_flags(s,t):return 'established_production_hierarchy_guard'
 if any(a.get('kind')=='parent' and a.get('accepted') and a.get('scope') and a.get('baseline_only') and a.get('query_unit_excluded') and a.get('independent_registry_units',0)>=2 and a.get('independent_source_units',0)>=2 and a.get('distinct_destinations')==1 for a in f.get('learned_aliases',[])):return 'independently_scoped_parent_alias'
 return None
_original_factor=engine.factor
def guarded_factor(s,t,*args,**kwargs):
 f=_original_factor(s,t,*args,**kwargs)
 if generic(s):
  established=proof(s,t,f);f['generic_building_safety']={'proof':established,'broad_area_alone_insufficient':True}
  if not established:
   flag='generic_building_without_independent_project_or_parent_proof';f['location_ok']=False;f['conflicts']=sorted(set(f['conflicts']+[flag]));f['location']={**f['location'],'conflicts':sorted(set(f['location'].get('conflicts',[])+[flag]))}
 return f

def declare():
 config={'rule':SAFETY_RULE,'safety_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'main_engine_sha256':hashlib.sha256((ROOT/'engine.py').read_bytes()).hexdigest(),'outcomes_inspected':False}
 save('engine-safety-declaration.json',config);print(json.dumps({'check':'DECLARED','safety_code_sha256':config['safety_code_sha256'],'outcomes_inspected':False}))
def read(name):return engine.read(name)
def run():
 declaration=json.loads((ROOT/'engine-safety-declaration.json').read_text());assert declaration['safety_code_sha256']==hashlib.sha256((ROOT/'engine-safety-declared.py').read_bytes()).hexdigest();assert declaration['main_engine_sha256']==hashlib.sha256((ROOT/'engine.py').read_bytes()).hexdigest()
 optimized_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 for a,b in [('results.jsonl','engine-raw-results.jsonl'),('metrics.json','engine-raw-metrics.json'),('engine-holdout.jsonl','engine-raw-holdout.jsonl')]:
  assert not (ROOT/b).exists(),b;shutil.copyfile(ROOT/a,ROOT/b)
 rawmetrics=json.loads((ROOT/'engine-raw-metrics.json').read_text())
 for name,expected in rawmetrics['input_sha256'].items():
  p=Path(name) if name.startswith('/') else ROOT/name
  assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,name
 focus=read('rows.jsonl');raw={r['row_key']:r for r in read('engine-raw-results.jsonl')};baseline=read('baseline-matched.jsonl');baseline_unique={r['source_event_id']:r for r in baseline}
 training=read('engine-training-pairs.jsonl');train=[({'source':p['source'],'source_unit_id':p['source_unit_id'],'source_event_id':p['source_event_id']},p['target']) for p in training]
 aliases=AliasModel(baseline_pairs=[{'source':{**p['source'],'raw_fields':p.get('raw_fields',{}),'source_unit_id':p['source_unit_id'],'source_event_id':p['source_event_id']},'target':p['target']} for p in training],places=json.loads(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json').read_text()))
 sizes=engine.SheetSizeEvidence()
 for r,t in train:sizes.observe(r['source'],[(t,200,[])])
 pools=engine.Pools(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite'));needed={engine.current_key(r) for r in baseline};targets={}
 for key,payload in pools.db.execute("SELECT json_extract(payload,'$.event_key'),payload FROM event WHERE family='sale'"):
  if 'sale:'+str(key) in needed:targets['sale:'+str(key)]=json.loads(payload)
 baseline_targets=[(r,targets[engine.current_key(r)]) for r in baseline]
 engine.factor=guarded_factor;cache={};changed=collections.Counter();results=[];replays=0
 for r in sorted(focus,key=lambda r:engine.Decimal(str(r['source'].get('amount_aed') or 0))):
  old=raw[r['row_key']];x=old
  if generic(r['source']) and old['status']=='new_supported_inferred':
   key=(r['source_event_id'],engine.digest(r['source']))
   if key not in cache:
    pool,rentals=pools.get(r['source'].get('amount_aed'));cache[key]=engine.select(r,pool,rentals,aliases,sizes);replays+=1
   x={**r,**cache[key]}
  if r.get('primary_cause')=='original_address_codes_contradict' and x['status']=='new_supported_inferred':x={**x,'status':'tentative','reason':'original_address_contradiction_retained','rule':'preferred_full_child_hypothesis_requires_review'}
  x={**x,'raw_profile_status':old['status'],'raw_profile_selected_event_key':(old.get('selected') or {}).get('event_key'),'safety_replayed':generic(r['source']) and old['status']=='new_supported_inferred'}
  if x['status']!=old['status']:changed[old['status']+' -> '+x['status']]+=1
  results.append((r,x))
 conflicts=engine.veto(results,[],baseline_targets)
 cats={c:{'rows':0,'statuses':collections.Counter(),'rules':collections.Counter(),'reasons':collections.Counter()} for c in engine.CAUSES}
 with (ROOT/'results.jsonl').open('w') as out:
  for r,x in results:
   out.write(json.dumps(x,sort_keys=True,default=str)+'\n');m=cats[r['primary_cause']];m['rows']+=1;m['statuses'][x['status']]+=1;m['rules'][str(x.get('rule'))]+=1;m['reasons'][x['reason']]+=1
 rawhold=read('engine-raw-holdout.jsonl');holdrows=[];hold_replays=0
 for old in sorted(rawhold,key=lambda r:engine.Decimal(str(r['source'].get('amount_aed') or 0))):
  r=baseline_unique[old['source_event_id']];x=old
  if generic(r['source']) and old['status']=='new_supported_inferred':
   pool,rentals=pools.get(r['source'].get('amount_aed'));new=engine.select(r,pool,rentals,aliases,sizes,mask=True);x={**old,**new};hold_replays+=1
  x={**x,'raw_profile_status':old['status'],'safety_replayed':generic(r['source']) and old['status']=='new_supported_inferred'};holdrows.append((r,x))
 holdconflicts=engine.veto([({**r,'source':engine.masked(r['source'])},x) for r,x in holdrows],[],train);hold=collections.Counter()
 with (ROOT/'engine-holdout.jsonl').open('w') as out:
  for r,x in holdrows:
   hold['weak_pairs']+=1;hold[x['status']]+=1
   if x['status']=='new_supported_inferred':
    hold['selected']+=1;hold['exact_event_agreement']+=x['selected']['event_key']==x['weak_event'];hold['same_property_agreement']+=x['selected']['property']==x['weak_property'];hold['different_property_collision']+=x['selected']['property']!=x['weak_property']
   out.write(json.dumps(x,sort_keys=True,default=str)+'\n')
 metrics={**rawmetrics,'raw_profile_statuses':rawmetrics['statuses'],'raw_profile_holdout':rawmetrics['holdout'],'fixed_categories':cats,'statuses':dict(collections.Counter(x['status'] for r,x in results)),'not_supported_rows':sum(x['status'] not in {'new_supported_inferred','already_live_recovered'} for r,x in results),'holdout':{'property_unit_holdout':hold},'conflicts':conflicts,'holdout_conflicts':holdconflicts,'safety_filter':{**declaration,'optimization_code_sha256':optimized_code_sha256,'optimization':'Demotion-only fast path: replay only previously supported generic/numeric building claims; all unsupported hypotheses remain unaccepted. Original pre-outcome rule/declaration preserved.','focus_frames_replayed':replays,'holdout_frames_replayed':hold_replays,'status_transitions_before_final_conflict_veto':dict(changed)},'sqlite_total_changes':pools.db.total_changes}
 assert pools.db.total_changes==0;assert metrics['statuses'].get('already_live_recovered')==8
 for r,x in results:
  if x['status']=='new_supported_inferred' and generic(r['source']):assert (x['selected'].get('generic_building_safety') or {}).get('proof')
 assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==optimized_code_sha256
 assert metrics['statuses'].get('new_supported_inferred',0)<=rawmetrics['statuses'].get('new_supported_inferred',0)
 save('metrics.json',metrics);print(json.dumps({'check':'PASS','focus_frames_replayed':replays,'holdout_frames_replayed':hold_replays,'raw_statuses':rawmetrics['statuses'],'validated_statuses':metrics['statuses'],'holdout':dict(hold)},sort_keys=True))
if __name__=='__main__':
 if '--declare' in sys.argv:declare()
 else:run()
