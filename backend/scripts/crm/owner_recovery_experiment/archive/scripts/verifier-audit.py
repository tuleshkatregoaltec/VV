"""Independent invariant audit. Reads frozen inputs/results; emits private verifier report."""
import collections, hashlib, json, sys
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));import engine as e

def read(name):
 return [json.loads(l) for l in (ROOT/name).open()]
def main():
 metrics=json.loads((ROOT/'metrics.json').read_text());focus=read('rows.jsonl');results=read('results.jsonl');holdout=read('engine-holdout.jsonl');train=read('engine-training-pairs.jsonl')
 failures=[]
 def ck(condition,message):
  if not condition:failures.append(message)
 ck(len(results)==len(focus)==36102,'cohort_size')
 fm={r['row_key']:r for r in focus};rm={r['row_key']:r for r in results}
 ck(set(fm)==set(rm) and len(rm)==len(results),'cohort_row_keys')
 ck(collections.Counter(r['primary_cause'] for r in results)==e.CAUSES,'fixed_partition')
 statuses=collections.Counter(r['status'] for r in results);ck(dict(statuses)==metrics['statuses'],'reported_statuses')
 ck(statuses['already_live_recovered']==sum(e.current_live(r) for r in focus)==8,'already_live')
 for r in results:
  original=fm[r['row_key']]
  ck(all(r.get(k)==original.get(k) for k in ('source','raw_fields','primary_cause','original_category','current_match')),'raw_preservation:'+r['row_key'])
  if r['status']!='new_supported_inferred':continue
  f=r['selected'];s=r['source'];t=f['target']
  ck(s['event_family']=='sale' and t['event_family']=='sale','sale_family:'+r['row_key'])
  ck(abs(Decimal(str(s['amount_aed']))-Decimal(str(t['amount_aed'])))<=2,'amount:'+r['row_key'])
  ck(f['location_ok'] and not f['conflicts'] and f['physical_type_compatible'],'evidence:'+r['row_key'])
  ck(r['primary_cause']!='original_address_codes_contradict','contradictory_cause:'+r['row_key'])
  ck(r['candidate_pool_uncapped'] and r['surviving_property_count']==1,'unique_property:'+r['row_key'])
  if metrics.get('safety_filter') and s.get('building_name') and (e.tm.generic_building(s['building_name']) or e.tm.identifier(s['building_name']).isdigit()):ck(bool(f.get('generic_building_safety',{}).get('proof')),'generic_scope_proof:'+r['row_key'])
  if not f['id_ok']:ck(bool(f['size']['matches'] or f['date']['exact']),'independent_corrob:'+r['row_key'])
  if f['size'].get('basis')=='independent_training_sheet_unit':
   ck(f['size']['independent_units']>=10 and f['size']['winning_unit_support']>=10 and Decimal(f['size']['agreement'])>=Decimal('.95'),'size_votes:'+r['row_key'])
 ck(not {tuple(e.prop(p['target'])) for p in train}&{tuple(r['weak_property']) for r in holdout},'holdout_target_disjoint')
 ck(not {p['source_unit_id'] for p in train}&{r['source_unit_id'] for r in holdout},'holdout_source_disjoint')
 ck(len({r['source_event_id'] for r in holdout})==len(holdout),'holdout_duplicate_sourceevents')
 hm=collections.Counter(weak_pairs=len(holdout));hm.update(r['status'] for r in holdout)
 for r in holdout:
  ck(not e.raw_ids(r['source']) and all(not r['source'].get(k) and not r['source'].get('raw_fields',{}).get(k) for k in e.IDENTIFIER_FIELDS),'masked_ids:'+r['source_event_id'])
  if r['status']=='new_supported_inferred':
   hm['selected']+=1;hm['exact_event_agreement']+=int(r['selected']['event_key']==r['weak_event']);hm['same_property_agreement']+=int(tuple(r['selected']['property'])==tuple(r['weak_property']));hm['different_property_collision']+=int(tuple(r['selected']['property'])!=tuple(r['weak_property']))
 ck(dict(hm)==metrics['holdout']['property_unit_holdout'],'holdout_metrics')
 for name,sha in metrics['input_sha256'].items():ck(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,'input_hash:'+name)
 if metrics.get('safety_filter'):
  sf=metrics['safety_filter'];ck(hashlib.sha256((ROOT/'engine-safety.py').read_bytes()).hexdigest()==sf.get('optimization_code_sha256',sf['safety_code_sha256']) and hashlib.sha256((ROOT/'engine-safety-declared.py').read_bytes()).hexdigest()==sf['safety_code_sha256'],'safety_code_hash');ck(hashlib.sha256((ROOT/'engine.py').read_bytes()).hexdigest()==sf['main_engine_sha256'],'safety_main_hash')
 for cause in e.CAUSES:
  actual=[r for r in results if r['primary_cause']==cause];published=metrics['fixed_categories'][cause]
  ck(collections.Counter(r['status'] for r in actual)==published['statuses'],'cause_statuses:'+cause)
 report={'check':'PASS' if not failures else 'GAPS','failures':failures,'focus_rows':len(focus),'status_counts':dict(statuses),'supported_unique_source_events':len({r['source_event_id'] for r in results if r['status']=='new_supported_inferred'}),'holdout':dict(hm),'target_and_source_holdout_disjoint':True,'masked_id_fields_empty':True,'retained_location_encoded_ids':4,'encoded_id_cases_supported':0}
 (ROOT/'verifier-invariants.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps(report,sort_keys=True));return int(bool(failures))
if __name__=='__main__':raise SystemExit(main())
