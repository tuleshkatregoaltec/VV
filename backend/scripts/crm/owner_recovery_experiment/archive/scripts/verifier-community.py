"""Read-only Rule C invariant and raw snapshot replay audit."""
import collections,json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));import engine as e;import community_fingerprint as c

def read(name):return [json.loads(l) for l in (ROOT/name).open()]
def main():
 summary=json.loads((ROOT/'community-summary.json').read_text());focus={r['row_key']:r for r in read('rows.jsonl')};results=read('community-results.jsonl');hold=read('community-holdout.jsonl');train=read('engine-training-pairs.jsonl');failures=[]
 def ck(condition,message):
  if not condition:failures.append(message)
 ck(len(results)==36102 and len({r['row_key'] for r in results})==36102 and {r['row_key'] for r in results}==set(focus),'cohort_keys')
 ck(dict(collections.Counter(r['status'] for r in results))==summary['statuses'],'status_counts')
 ck(collections.Counter(r['primary_cause'] for r in results)==e.CAUSES,'fixed_causes')
 for name,sha in json.loads((ROOT/'community-input-manifest.json').read_text()).items():ck(hashlib.sha256(Path(name).read_bytes()).hexdigest()==sha,'input_hash:'+name)
 places=json.loads(c.PLACES.read_text());communities=c.Communities(places);aliases=c.AliasModel([{'source':{**p['source'],'source_event_id':p['source_event_id'],'source_unit_id':p['source_unit_id'],'raw_fields':p['raw_fields']},'target':p['target']} for p in train],places=places);sizes=e.SheetSizeEvidence()
 for p in train:sizes.observe(p['source'],[(p['target'],200,[])])
 supported=[r for r in results if r['status']=='conditional_rule_c_candidate']
 for r in supported:
  original=focus[r['row_key']];s=c.source_frame(original);t=r['selected']['target'];size,se=e.source_size(s,sizes)
  ck(e.tm.amounts_match(s['amount_aed'],t['amount_aed']),'amount:'+r['row_key']);ck(e.day(s['transaction_date'])==e.day(t['transaction_date']),'exact_day:'+r['row_key'])
  ck(bool(size and e.tm.sizes_match(size,t['size_sqft'])),'size:'+r['row_key']);ck(bool(c.physical_kind(s['property_type'])) and c.physical_kind(s['property_type'])==c.physical_kind(t['property_type']),'type:'+r['row_key'])
  ck(r['near_competitor_count']==0 and not r['candidate_evidence']['conflicts'],'competitors_or_conflicts:'+r['row_key']);ck(original['primary_cause']!='original_address_codes_contradict','contradictory_cause:'+r['row_key'])
 encoded={r['source_event_id'] for r in json.loads((ROOT/'verifier-holdout-encoded-identifiers.json').read_text())};excluded={r['source_event_id'] for r in hold if r['status']=='excluded_location_identifier_leakage'};ck(encoded<=excluded,'four_encoded_ids_excluded')
 ck(len(hold)==1839 and len({r['source_event_id'] for r in hold})==1839,'holdout_cohort')
 hm=collections.Counter(weak_pairs=len(hold));hm['excluded_location_identifier_leakage']=len(excluded);hm['evaluated_masked_pairs']=len(hold)-len(excluded)
 for r in hold:
  if r['status']=='excluded_location_identifier_leakage':continue
  hm[r['status']]+=1
  if r['status']=='conditional_rule_c_candidate':
   hm['selected']+=1;hm['same_event_agreement']+=r['selected']['event_key']==r['weak_event'];hm['same_property_agreement']+=r['selected']['property']==r['weak_property'];hm['different_property_collision']+=r['selected']['property']!=r['weak_property']
 ck(dict(hm)==summary['holdout'],'holdout_metrics')
 pools=e.Pools(c.SNAPSHOT)
 class ReferenceIndex:
  def query(self,community,amount,date,near=False):
   rows,_=pools.get(amount)
   for t in rows:
    if communities.target(t)!=community:continue
    td=e.day(t.get('transaction_date'))
    if (near and (td is None or abs((td-date).days)<=14)) or (not near and td==date):yield t
 replays=[];seen=set()
 for r in sorted(supported,key=lambda r:r['row_key']):
  uid=(r['source_event_id'],e.digest(focus[r['row_key']]['source']))
  if uid in seen:continue
  seen.add(uid);actual=c.select(focus[r['row_key']],ReferenceIndex(),communities,aliases,sizes);same=actual['status']==r['status'] and actual['selected']['event_key']==r['selected']['event_key'];ck(same,'raw_snapshot_replay:'+r['row_key']);replays.append({'row_key':r['row_key'],'same':same,'full_sale_pool_size':len(pools.rows)})
  if len(replays)>=25:break
 baseline={r['source_event_id']:r for r in read('baseline-matched.jsonl')};hreplays=[]
 for r in sorted(hold,key=lambda r:r['source_event_id']):
  if r['status']!='conditional_rule_c_candidate':continue
  actual=c.select(c.masked_row(baseline[r['source_event_id']]),ReferenceIndex(),communities,aliases,sizes);same=actual['status']==r['status'] and actual['selected']['event_key']==r['selected']['event_key'];ck(same,'masked_raw_snapshot_replay:'+r['source_event_id']);hreplays.append({'source_event_id':r['source_event_id'],'same':same,'full_sale_pool_size':len(pools.rows)})
  if len(hreplays)>=20:break
 report={'check':'PASS' if not failures else 'GAPS','failures':failures,'focus_rows':len(results),'conditional_rows':len(supported),'holdout':dict(hm),'four_encoded_ids_excluded':encoded<=excluded,'raw_snapshot_replays':replays,'holdout_raw_snapshot_replays':hreplays,'sqlite_changes':pools.db.total_changes};(ROOT/'verifier-community.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ('raw_snapshot_replays','holdout_raw_snapshot_replays')},sort_keys=True));print('independent_raw_snapshot_replays',len(replays),'holdout',len(hreplays))
if __name__=='__main__':main()
