"""Independent final repair invariants and uncapped raw-pool positive replays."""
import json,sys,collections,hashlib,importlib.util
from pathlib import Path
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P));import engine as e;import community_fingerprint as c
spec=importlib.util.spec_from_file_location('verifier_c5_profile',P/'community-c5.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
read=lambda n:[json.loads(l) for l in (P/n).open()]
def main():
 focus={r['row_key']:r for r in read('rows.jsonl')};train=read('engine-training-pairs.jsonl');places=json.loads(c.PLACES.read_text());communities=c.Communities(places);sizes=e.SheetSizeEvidence();aliases=c.AliasModel([{'source':{**r['source'],'source_event_id':r['source_event_id'],'source_unit_id':r['source_unit_id'],'raw_fields':r['raw_fields']},'target':r['target']} for r in train],places=places)
 for r in train:sizes.observe(r['source'],[(r['target'],200,[])])
 pairs=[({'source':r['source'],'source_unit_id':r['source_unit_id'],'source_event_id':r['source_event_id']},r['target']) for r in train];repair=m.Repair((json.loads(l) for l in (P/'all-rows.jsonl').open()),pairs,communities)
 pools=e.Pools(c.SNAPSHOT)
 def candidates(comm,amount):
  out=[]
  for t in pools.get(amount)[0]:
   member=communities.memberships(t)
   if comm in member['possible'] or '__unscoped__' in member['possible']:out.append({**t,'_community_positive_evidence':member['definite']==[comm]})
  return out
 class RawIndex:
  def query(self,comm,amount,day,near=False):
   for t in candidates(comm,amount):
    d=e.day(t.get('transaction_date'))
    if (near and (d is None or abs((d-day).days)<=14)) or (not near and d==day):yield t
 m.c4.history=lambda idx,comm,amount:candidates(comm,amount)
 outputs={};all_checks=[]
 for mode in ('exact','history'):
  name='community-c5-'+mode;results=read(name+'-results.jsonl');summary=json.loads((P/(name+'-summary.json')).read_text());status='conditional_rule_c5_'+mode+'_candidate';positive=[r for r in results if r['status']==status]
  assert len(results)==36102 and {r['row_key'] for r in results}==set(focus) and collections.Counter(r['status'] for r in results)==summary['statuses']
  contexts=collections.defaultdict(set)
  for r in train:
   source=r['source'];key=(m.basename(source.get('source_filename')),source.get('source_sheet'));contexts[key].add((r['source_unit_id'],e.prop(r['target']),communities.target(r['target']) or '__unknown_catalog_community__'))
  for r in positive:
   original=focus[r['row_key']];assert original['primary_cause']!='original_address_codes_contradict';t=r['selected']['target'];assert e.tm.amounts_match(original['source']['amount_aed'],t['amount_aed']);ev=r.get('community_repair')
   if ev:
    assert ev['original_raw_master_project']==original['raw_fields']['master_project'] and ev['raw_fields_preserved'] and ev['sequence']['source_row']==original['row'];assert int(ev['sequence']['original_suffix'])-int(original['row'])==ev['sequence']['suffix_minus_row'];support=ev['candidate_excluded_training_support'];assert support['accepted'] and support['candidate_target_property_excluded'] and support['query_source_unit_excluded'] and support['community_purity']=='1' and support['unknown_community_properties']==0
    key=(m.basename(original['filename']),original['sheet']);kept={(u,p,comm) for u,p,comm in contexts[key] if u!=original['source_unit_id'] and p!=e.prop(t)};assert len({p for u,p,comm in kept})==support['independent_properties'] and len({u for u,p,comm in kept})==support['independent_source_units'] and {comm for u,p,comm in kept}=={support['canonical_community']};assert support['independent_properties']>=10 and support['independent_source_units']>=10
   if mode=='exact':assert e.day(original['source']['transaction_date'])==e.day(t['transaction_date']) and r['near_competitor_count']==0
   else:assert r['history_competitor_count']==0 and r['date_is_not_selector']
  replays=[];seen=set()
  for r in sorted(positive,key=lambda r:r['row_key']):
   original=focus[r['row_key']];uid=(r['source_event_id'],e.digest(original['source']))
   if uid in seen:continue
   seen.add(uid);before=e.digest(original);actual=m.select(original,RawIndex(),communities,aliases,sizes,repair,mode);assert e.digest(original)==before and actual['status']==r['status'] and actual['selected']['event_key']==r['selected']['event_key'];replays.append({'row_key':r['row_key'],'full_sale_pool_size':len(pools.rows),'same_event':True,'input_preserved':True})
   if len(replays)>=12:break
  hold=read(name+'-holdout.jsonl');selected=[r for r in hold if r['status']==status];different=sum(r['selected']['property']!=r['weak_property'] for r in selected);assert len(hold)==1839 and len(selected)==summary['holdout']['selected'] and different==summary['holdout'].get('different_property_collision',0)
  outputs[mode]={'positive_rows':len(positive),'repaired_positive_rows':sum(bool(r.get('community_repair')) for r in positive),'uncapped_raw_pool_replays':len(replays),'holdout_selected':len(selected),'holdout_different_property':different,'repaired_masked_rows':summary['holdout'].get('repaired_masked_rows',0),'repair_not_empirically_tested_in_holdout':summary['holdout'].get('repaired_masked_rows',0)==0,'replays':replays}
 for name,sha in json.loads((P/'community-c5-input-manifest.json').read_text()).items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==sha,name
 report={'check':'PASS','profiles':outputs,'all_repair_support_counts_independently_recomputed':True,'raw_source_labels_preserved':True,'sqlite_total_changes':pools.db.total_changes};(P/'verifier-c5-final.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({**report,'profiles':{k:{a:b for a,b in v.items() if a!='replays'} for k,v in outputs.items()}}))
if __name__=='__main__':main()
