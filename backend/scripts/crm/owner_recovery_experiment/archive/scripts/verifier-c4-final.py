"""Final corrected retrieval: explain each different-property holdout outcome."""
import json,sys,sqlite3,collections,importlib.util
from pathlib import Path
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P));import engine as e;import community_fingerprint as c
spec=importlib.util.spec_from_file_location('final_c4',P/'community-c4.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
read=lambda n:[json.loads(l) for l in (P/n).open()]
train=read('engine-training-pairs.jsonl');baseline={r['source_event_id']:r for r in read('baseline-matched.jsonl')};holds=read('community-c4-holdout.jsonl');places=json.loads(c.PLACES.read_text());communities=c.Communities(places);sizes=e.SheetSizeEvidence();aliases=c.AliasModel([{'source':{**r['source'],'source_event_id':r['source_event_id'],'source_unit_id':r['source_unit_id'],'raw_fields':r['raw_fields']},'target':r['target']} for r in train],places=places)
for r in train:sizes.observe(r['source'],[(r['target'],200,[])])
pools=e.Pools(c.SNAPSHOT);idx=sqlite3.connect('file:'+str(P/'community-index.sqlite')+'?mode=ro&immutable=1',uri=True)
def fullhistory(index,community,amount):
 out=[]
 for t in pools.get(amount)[0]:
  membership=communities.memberships(t)
  if community in membership['possible'] or '__unscoped__' in membership['possible']:out.append({**t,'_community_positive_evidence':membership['definite']==[community]})
 return out
m.history=fullhistory
collisions=[r for r in holds if r['status']==m.STATUS and r['selected']['property']!=r['weak_property']];out=[]
for r in collisions:
 original=baseline[r['source_event_id']];masked=c.masked_row(original);s=c.source_frame(masked);comm,_=communities.source(masked);weak=json.loads(idx.execute('select payload from baseline_target where event_key=?',(r['weak_event'],)).fetchone()[0]);hs,se=m.hypotheses(s,sizes);weaksize=e.tm.positive_decimal(weak.get('size_sqft'));weaktype=c.physical_kind(weak.get('property_type'));samekind=m.broad_type(s.get('property_type')) or not weaktype or weaktype==c.physical_kind(s.get('property_type'));typeok=samekind and not e.tm.physical_types_conflict(s.get('property_type'),weak.get('property_type'));sizeok=weaksize is None or any(e.tm.sizes_match(v,weaksize) for label,v in hs);amountok=e.tm.amounts_match(s['amount_aed'],weak['amount_aed']);membership=communities.memberships(weak);scopeok=comm in membership['possible'] or '__unscoped__' in membership['possible'];pool,_=pools.get(s['amount_aed']);inraw=any(e.ek(t)==r['weak_event'] for t in pool);actual=m.select(masked,None,communities,aliases,sizes);assert actual['status']==r['status'] and actual['selected']['event_key']==r['selected']['event_key'];assert not (scopeok and amountok and typeok and sizeok), 'Valid omitted competitor remains'
 out.append({'source_event_id':r['source_event_id'],'weak_event':r['weak_event'],'selected_event':r['selected']['event_key'],'source_community':comm,'weak_possible_communities':membership['possible'],'weak_amount':weak['amount_aed'],'source_amount':s['amount_aed'],'weak_size':str(weaksize),'size_hypotheses':[(l,str(v)) for l,v in hs],'source_type':s.get('property_type'),'weak_type':weak.get('property_type'),'weak_present_in_raw_amount_pool':inraw,'amount_compatible':amountok,'type_compatible':typeok,'size_compatible_or_unknown':sizeok,'scope_compatible':scopeok,'replay_same_selected_event':True})
oldids={r['source_event_id'] for r in json.loads((P/'verifier-community-membership-gap.json').read_text())['cases']};newselected={r['source_event_id'] for r in holds if r['status']==m.STATUS};old_demoted=not oldids&newselected
report={'check':'PASS','final_selected':sum(r['status']==m.STATUS for r in holds),'different_property_disagreements':len(collisions),'old_seven_selections_removed':old_demoted,'all_final_disagreements_explained_by_declared_size_type_amount_scope_gate':True,'criteria_counts':{key:sum(not r[key] for r in out) for key in ('amount_compatible','type_compatible','size_compatible_or_unknown','scope_compatible')},'cases':out,'sqlite_total_changes':pools.db.total_changes};(P/'verifier-c4-final.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='cases'}))
