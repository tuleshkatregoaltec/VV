"""Separate full-child namespace/parent-role probe; never changes main classifications."""
import collections, importlib.util, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('role_audit',ROOT/'engine-role-reconciliation.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
e=audit.e
sys.path.insert(0,str(ROOT));from aliases import AliasModel
from app.crm.owner_namespaces import parse_r3,source_namespace

def run():
 focus=[r for r in e.read('rows.jsonl') if r['primary_cause']=='original_address_codes_contradict'];training=e.read('engine-training-pairs.jsonl');baseline=e.read('baseline-matched.jsonl')
 model=AliasModel(baseline_pairs=[{'source':{**p['source'],'raw_fields':p['raw_fields'],'source_unit_id':p['source_unit_id']},'target':p['target']} for p in training],places=json.loads(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json').read_text()))
 sizes=e.SheetSizeEvidence()
 for p in training:sizes.observe(p['source'],[(p['target'],200,[])])
 pools=e.Pools(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite'));cache={};results=[];rejections=collections.Counter();stages=collections.Counter();examples=[]
 for row in focus:
  key=(row['source_event_id'],e.digest(row['source']))
  if key not in cache:
   s={**row['source'],'source_unit_id':row['source_unit_id'],'source_event_id':row['source_event_id'],'raw_fields':row['raw_fields'],'_declared_size_unit':row.get('source_declared_size_unit')};raw=s.get('original_identifiers') or {};code=e.tm.identifier(str(raw.get('building_number') or ''));parsed=parse_r3(code);number=parsed[1] if parsed else '';amount=e.tm.positive_decimal(s.get('amount_aed'));size,size_evidence=e.source_size(s,sizes);valid=[];seen=set();localreject=collections.Counter();candidate_count=0;namespace_count=0;role_count=0
   if amount and code:
    lo=float(amount-2);hi=float(amount+2);eps=max(abs(lo),abs(hi),1)*2e-15
    sql="SELECT e.payload FROM property_lookup p JOIN event e ON e.rowid=p.event_rowid WHERE (p.identifier=? OR (?<>'' AND p.villa_number=?)) AND e.family='sale' AND e.amount BETWEEN ? AND ?"
    for (payload,) in pools.db.execute(sql,(code,number,number,lo-eps,hi+eps)):
     t=json.loads(payload)
     if not any(abs(v-amount)<=e.Decimal(2) for _,v in e.tm._amounts(t)):continue
     identity=(e.ek(t),e.prop(t))
     if identity in seen:continue
     seen.add(identity);candidate_count+=1;ns=source_namespace(s,t);direct=code==e.tm.identifier(str(t.get('unit_number') or ''))
     if not (direct or ns):localreject['no_exact_full_child_or_established_namespace']+=1;continue
     namespace_count+=1;f=e.factor(s,t,model,size,size_evidence);x=audit.evaluate({**row,'selected':f,'reason':'role_candidate_before_event_selection'})
     if not x['all_original_identifier_roles_explained']:
      localreject.update(x['rejections']);continue
     role_count+=1;f['role_reconciliation']={'full_child_proof':'exact_full_code' if direct else 'established_full_R3_namespace','explained_original_roles':x['explained_roles'],'numeric_label_not_used_without_full_namespace':True};valid.append((t,f))
   reason='no_fully_explained_child_parent_candidate';chosen=None
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
     reason='all_roles_and_unique_event' if chosen else 'ambiguous_or_nearby_event'
   value={'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'status':'new_supported_inferred' if chosen else 'unresolved','rule':'conditional_full_child_and_independent_parent_roles' if chosen else None,'reason':reason,'selected':chosen[1] if chosen else None,'indexed_identity_candidates':candidate_count,'full_child_namespace_candidates':namespace_count,'all_roles_explained_candidates':role_count,'rejection_counts':dict(localreject),'valid_event_count':len(valid),'all_indexed_full_child_hypotheses_uncapped':True}
   cache[key]=value;stages.update({'source_frames':1,'indexed_identity_candidates':candidate_count,'full_child_namespace_candidates':namespace_count,'all_roles_explained_candidates':role_count});rejections.update(localreject)
  results.append((row,{**cache[key]}))
 needed={e.current_key(r) for r in baseline};targets={}
 for key,payload in pools.db.execute("SELECT json_extract(payload,'$.event_key'),payload FROM event WHERE family='sale'"):
  if 'sale:'+str(key) in needed:targets['sale:'+str(key)]=json.loads(payload)
 conflict=e.veto(results,[],[(r,targets[e.current_key(r)]) for r in baseline]);counts=collections.Counter();props=set();events=set();sourceevents=set()
 with (ROOT/'engine-role-indexed.jsonl').open('w') as out:
  for row,x in results:
   if x['status']=='new_supported_inferred':
    x['status']='conditional_role_reconciliation_proposal';props.add(tuple(x['selected']['property']));events.add(x['selected']['event_key']);sourceevents.add(x['source_event_id'])
    if len(examples)<8:examples.append({**row,**x})
   counts[x['status']]+=1;out.write(json.dumps({**row,**x},sort_keys=True,default=str)+'\n')
 summary={'check':'PASS','rows':len(focus),'status_counts':dict(counts),'stages':dict(stages),'rejections':dict(rejections),'conflicts':conflict,'conditional_unique_source_events':len(sourceevents),'conditional_unique_registry_events':len(events),'conditional_unique_properties':len(props),'examples':examples,'main_classifications_changed':0,'sqlite_total_changes':pools.db.total_changes,'declaration':json.loads((ROOT/'engine-role-reconciliation-declaration.json').read_text()),'retrieval':'Indexed exact full child or numeric registry aliases, always proven by source_namespace full-code+community+numeric-label agreement; complete ±2 AED band, no cap. Other namespaces and suffix-only matches rejected.'}
 assert pools.db.total_changes==0;e.save('engine-role-indexed.json',summary);print(json.dumps({k:v for k,v in summary.items() if k not in ('examples','declaration')},sort_keys=True))
if __name__=='__main__':run()
