"""Audit, never promote, contradiction candidates against predeclared full-role proof."""
import collections, hashlib, importlib.util, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('role_engine',ROOT/'engine.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
from app.crm.owner_namespaces import source_namespace

def evaluate(r):
 s=r['source'];f=r.get('selected') or {};t=f.get('target') or {};raw=s.get('original_identifiers') or {};audits=f.get('learned_aliases',[]);reasons=[];explained=[]
 child=e.tm.identifier(str(raw.get('building_number') or ''));target=e.tm.identifier(str(t.get('unit_number') or ''));namespace=source_namespace(s,t) if t else None
 if not child or not (child==target or namespace):reasons.append('no_exact_full_building_child_or_established_namespace')
 else:explained.append({'field':'building_number','role':'full_child','value':raw.get('building_number'),'proof':'exact_full_code' if child==target else 'established_full_R3_namespace'})
 for k in ('unit_number','property_number','plot_number','plot_pre_reg_number'):
  value=e.tm.identifier(str(raw.get(k) or ''))
  if not value:continue
  if k=='unit_number' and (value==target or (namespace and value==namespace[2])):
   explained.append({'field':k,'value':raw[k],'role':'same_child'});continue
  matches=[a for a in audits if a.get('kind')=='parent' and a.get('source_field')==k and a.get('source_key')==value and a.get('accepted') and a.get('scope') and a.get('baseline_only') and a.get('query_unit_excluded') and a.get('distinct_destinations')==1 and a.get('independent_registry_units',0)>=3 and a.get('independent_source_units',0)>=3]
  if matches:explained.append({'field':k,'value':raw[k],'role':'independent_parent','proof':matches})
  else:reasons.append('unexplained_original_role:'+k)
 label=e.tm.identifier(str((r.get('raw_fields') or {}).get('building_name') or s.get('building_name') or ''))
 if label.isdigit():
  if namespace:explained.append({'field':'building_name','value':label,'role':'same_child_numeric_label','proof':'established_full_R3_namespace'})
  else:reasons.append('unexplained_numeric_building_label')
 # Only conflicts explicitly established by a known namespace can be explained.
 for flag in f.get('conflicts',[]):
  if namespace and (flag=='explicit_building_label_conflict' or flag=='role_correct_original_child_conflict:building_number'):continue
  reasons.append('residual_conflict:'+flag)
 if not f.get('location_ok') and not namespace:reasons.append('no_qualified_location')
 if not f.get('physical_type_compatible'):reasons.append('physical_type_conflict')
 if f.get('size',{}).get('value_sqft') and not f.get('size',{}).get('matches'):reasons.append('independent_size_disagreement')
 if r.get('conflict_veto'):reasons.extend(r['conflict_veto'])
 # Passing role explanation alone does not establish event uniqueness.
 only_blanket=r.get('reason')=='original_address_contradiction_retained'
 return {'row_key':r['row_key'],'source_event_id':r['source_event_id'],'source_unit_id':r['source_unit_id'],'filename':r['filename'],'sheet':r['sheet'],'row':r['row'],'original_category':r['primary_cause'],'source':s,'raw_fields':r.get('raw_fields'),'selected':f,'all_original_identifier_roles_explained':not reasons,'candidate_rejected_only_by_blanket_category':only_blanket,'conditional_supported_proposal':not reasons and only_blanket,'explained_roles':explained,'rejections':sorted(set(reasons))}

def run():
 source=ROOT/'engine-raw-results.jsonl'
 if not source.exists():source=ROOT/'results.jsonl'
 counts=collections.Counter();reasons=collections.Counter();examples=[];n=0
 with (ROOT/'engine-role-reconciliation.jsonl').open('w') as out:
  for line in source.open():
   r=json.loads(line)
   if r['primary_cause']!='original_address_codes_contradict':continue
   n+=1;x=evaluate(r);counts[r['status']]+=1;counts['blocked_only_by_blanket_category']+=x['candidate_rejected_only_by_blanket_category'];counts['all_roles_explained']+=x['all_original_identifier_roles_explained'];counts['conditional_supported_proposal']+=x['conditional_supported_proposal'];reasons.update(x['rejections'])
   out.write(json.dumps(x,sort_keys=True,default=str)+'\n')
   if x['conditional_supported_proposal'] and len(examples)<8:examples.append(x)
 assert n==5341
 result={'check':'PASS','rows':n,'counts':dict(counts),'rejection_counts':dict(reasons),'conditional_examples':examples,'changes_to_main_or_validated_classification':0,'declaration_sha256':hashlib.sha256((ROOT/'engine-role-reconciliation-declaration.json').read_bytes()).hexdigest(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'limits':'Role evidence audit over selected uncapped-pool hypotheses; passing roles alone does not override amount, size/date event ambiguity or conflict vetoes. Original contradiction category remains fixed.'}
 e.save('engine-role-reconciliation.json',result);print(json.dumps({k:v for k,v in result.items() if k!='conditional_examples'},sort_keys=True))
if __name__=='__main__':run()
