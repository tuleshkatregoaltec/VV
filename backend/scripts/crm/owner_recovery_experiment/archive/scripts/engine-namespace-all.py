"""Bounded all-five production R3 namespace probe; original classifications untouched."""
import collections, hashlib, importlib.util, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('namespace_engine',ROOT/'engine.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
sys.path.insert(0,str(ROOT));from aliases import AliasModel
from app.crm.owner_namespaces import parse_r3,source_namespace
from app.crm.owner_matching_policy import qualified
from app.market.reference import property_name_lookup_key
RULE={'version':'existing-r3-namespace-all-five-1','scope':'All five original categories, preserving fixed row membership; contradiction category remains in separate strict role audit.','identity':'Only full original R3 BuildingNo plus independently matching named project/community and matching original numeric building label through existing source_namespace. No suffix-only or new Emirates namespace guesses.','project_normalization':'Known master-child label Arabian Ranches III/3/lll - COMMUNITY may be canonicalized only when COMMUNITY exactly equals the complete original R3 code namespace. Both original and normalized labels are retained; numeric building disagreements are never corrected.','selection':'Full indexed child aliases within Decimal +/-2 AED, no cap; same learned-unit/size/14-day-date and global reuse/source-property vetoes as frozen engine.','classification':'Separate conditional namespace profile; no original ledger classifications or live assignments change.'}
def normalize_context(source):
 s={**source};s['raw_location_fields']={**source.get('raw_location_fields',{})};full=parse_r3((source.get('original_identifiers') or {}).get('building_number'));proof=[]
 if not full:return s,proof
 for container,name in ((s,'project_name'),(s['raw_location_fields'],'project_name')):
  value=str(container.get(name) or '');m=re.fullmatch(r'arabian\s+ranches\s+(?:iii|lll|3)\s*[-:]\s*(.+)',value.strip(),re.I)
  if m and property_name_lookup_key(m[1])==full[0]:
   replacement=m[1].strip() if container is s else 'Arabian Ranches III - '+m[1].strip();container[name]=replacement;proof.append({'field':'project_name' if container is s else 'raw_location_fields.project_name','original':value,'normalized':replacement,'independent_full_original_code':(source.get('original_identifiers') or {}).get('building_number'),'matching_named_community':full[0]})
 return s,proof

def run():
 e.save('engine-namespace-all-rule.json',{'rule':RULE,'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
 focus=e.read('rows.jsonl');training=e.read('engine-training-pairs.jsonl');baseline=e.read('baseline-matched.jsonl');pools=e.Pools(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite'));sizes=e.SheetSizeEvidence()
 for p in training:sizes.observe(p['source'],[(p['target'],200,[])])
 model=AliasModel(baseline_pairs=[{'source':{**p['source'],'raw_fields':p['raw_fields'],'source_unit_id':p['source_unit_id']},'target':p['target']} for p in training],places=json.loads(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json').read_text()))
 cache={};results=[];stages=collections.Counter();rejections=collections.Counter()
 for row in focus:
  key=(row['source_event_id'],e.digest(row['source']))
  if key not in cache:
   s,normalization=normalize_context(row['source']);s.update(source_unit_id=row['source_unit_id'],source_event_id=row['source_event_id'],raw_fields=row['raw_fields'],_declared_size_unit=row.get('source_declared_size_unit'));raw=s.get('original_identifiers') or {};code=e.tm.identifier(str(raw.get('building_number') or ''));parsed=parse_r3(code);amount=e.tm.positive_decimal(s.get('amount_aed'));size,size_evidence=e.source_size(s,sizes);valid=[];seen=set();local=collections.Counter()
   if parsed and amount:
    stages['frames_with_full_original_R3_code']+=1;lo=float(amount-2);hi=float(amount+2);eps=max(abs(lo),abs(hi),1)*2e-15
    for (payload,) in pools.db.execute("SELECT e.payload FROM property_lookup p JOIN event e ON e.rowid=p.event_rowid WHERE (p.identifier=? OR p.villa_number=?) AND e.family='sale' AND e.amount BETWEEN ? AND ?",(code,parsed[1],lo-eps,hi+eps)):
     t=json.loads(payload)
     if not any(abs(v-amount)<=e.Decimal(2) for _,v in e.tm._amounts(t)):continue
     identity=e.ek(t),e.prop(t)
     if identity in seen:continue
     seen.add(identity);stages['indexed_sale_hypotheses']+=1;ns=source_namespace(s,t);production=qualified(s,t) if ns else None
     if not ns or not production:local['original_full_code_or_context_conflict']+=1;continue
     stages['production_namespace_proven_candidates']+=1
     f=e.factor(s,t,model,size,size_evidence);f['production_namespace_proof']={'full_original_child_code':raw.get('building_number'),'canonical_namespace':list(ns),'source_project_normalization':normalization,'production_rules':production[1],'original_factor_conflicts':f['conflicts'],'raw_numeric_building_label':row['raw_fields'].get('building_name'),'raw_original_identifiers':raw};valid.append((t,f))
   reason='no_existing_full_namespace_candidate';chosen=None
   if valid:
    if size and any(not e.tm.positive_decimal(t.get('size_sqft')) for t,f in valid):reason='unknown_target_size_prevents_uniqueness';valid=[]
    elif size:
     valid=[(t,f) for t,f in valid if f['size']['matches']]
     if not valid:reason='independent_size_disagrees'
    props={e.prop(t) for t,f in valid}
    if len(props)>1:reason='multiple_properties_date_cannot_override'
    elif len(props)==1:
     if len(valid)==1:chosen=valid[0]
     else:
      target=e.tm.exact_date_event(s.get('transaction_date'),[t for t,f in valid]);chosen=next(((t,f) for t,f in valid if t is target),None)
     reason='production_full_namespace_unique_event' if chosen else 'ambiguous_or_nearby_event'
   status='new_supported_inferred' if chosen else 'unresolved'
   if row['primary_cause']=='original_address_codes_contradict' and chosen:status='tentative';reason='original_contradiction_requires_separate_all_role_proof'
   if e.current_live(row):status='already_live_recovered';reason='matched_before_offline_experiment'
   cache[key]={'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'status':status,'rule':'existing_full_R3_namespace_conditional' if chosen else None,'reason':reason,'selected':chosen[1] if chosen else None,'normalization':normalization,'indexed_child_hypotheses':len(seen),'valid_event_count':len(valid),'rejection_counts':dict(local),'uncapped_indexed_full_identity_pool':True}
   stages['source_frames']+=1;rejections.update(local)
  x={**cache[key]}
  if row['primary_cause']=='original_address_codes_contradict' and x['status']=='new_supported_inferred':x.update(status='tentative',reason='original_contradiction_requires_separate_all_role_proof')
  results.append((row,x))
 needed={e.current_key(r) for r in baseline};targets={}
 for key,payload in pools.db.execute("SELECT json_extract(payload,'$.event_key'),payload FROM event WHERE family='sale'"):
  if 'sale:'+str(key) in needed:targets['sale:'+str(key)]=json.loads(payload)
 conflicts=e.veto(results,[],[(r,targets[e.current_key(r)]) for r in baseline]);counts=collections.Counter();categories=collections.defaultdict(collections.Counter);events=set();props=set();examples=[]
 with (ROOT/'engine-namespace-all.jsonl').open('w') as out:
  for row,x in results:
   if x['status']=='new_supported_inferred':
    x['status']='conditional_existing_namespace_proposal';events.add(x['selected']['event_key']);props.add(tuple(x['selected']['property']))
    if len(examples)<10:examples.append({**row,**x})
   counts[x['status']]+=1;categories[row['primary_cause']][x['status']]+=1;out.write(json.dumps({**row,**x},sort_keys=True,default=str)+'\n')
 summary={'check':'PASS','rows':len(focus),'status_counts':dict(counts),'categories':dict(categories),'stages':dict(stages),'rejections':dict(rejections),'conflicts':conflicts,'conditional_registry_events':len(events),'conditional_properties':len(props),'examples':examples,'main_classifications_changed':0,'sqlite_total_changes':pools.db.total_changes,'rule':RULE,'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()};assert pools.db.total_changes==0;e.save('engine-namespace-all.json',summary);print(json.dumps({k:v for k,v in summary.items() if k not in ('examples','rule')},sort_keys=True))
if __name__=='__main__':run()
