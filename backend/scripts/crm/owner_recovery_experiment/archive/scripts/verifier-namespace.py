"""Independent uncapped global sale-pool replay of bounded namespace proposals."""
import json,sys,collections,hashlib,importlib.util
from pathlib import Path
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P));import engine as e
spec=importlib.util.spec_from_file_location('verifier_namespace_profile',P/'engine-namespace-all.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
read=lambda n:[json.loads(l) for l in (P/n).open()]
rows=read('engine-namespace-delivery.jsonl');focus={r['row_key']:r for r in read('rows.jsonl')};train=read('engine-training-pairs.jsonl');baseline=read('baseline-matched.jsonl');sizes=e.SheetSizeEvidence()
for p in train:sizes.observe(p['source'],[(p['target'],200,[])])
assert len(rows)==171 and len({r['row_key'] for r in rows})==171
pools=e.Pools('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite');cache={};checks=[];tiers=collections.Counter();selected_targets={}
for row in sorted(rows,key=lambda r:e.Decimal(str(r['source']['amount_aed']))):
 original=focus[row['row_key']];assert all(row[k]==original[k] for k in ('source','raw_fields','primary_cause'));assert row['primary_cause']=='full_identifier_not_in_same_price_scoped_sales'
 s,proof=m.normalize_context(row['source']);s.update(source_unit_id=row['source_unit_id'],source_event_id=row['source_event_id'],raw_fields=row['raw_fields'],_declared_size_unit=original['source_declared_size_unit']);uid=(row['source_event_id'],e.digest(row['source']));chosen=None
 if uid not in cache:
  pool,_=pools.get(s['amount_aed']);valid=[t for t in pool if m.source_namespace(s,t) and m.qualified(s,t)];size,se=e.source_size(s,sizes)
  if size:
   assert not any(not e.tm.positive_decimal(t.get('size_sqft')) for t in valid);valid=[t for t in valid if e.tm.sizes_match(size,t['size_sqft'])]
  assert len({e.prop(t) for t in valid})==1
  chosen=valid[0] if len(valid)==1 else e.tm.exact_date_event(s['transaction_date'],valid)
  assert chosen is not None;cache[uid]=(chosen,len(pool),len(valid),se);selected_targets[e.ek(chosen)]=chosen
 chosen,n,validn,se=cache[uid];assert e.ek(chosen)==row['selected']['event_key'];ns=m.source_namespace(s,chosen);assert ns and e.tm.amounts_match(s['amount_aed'],chosen['amount_aed'])
 rawlabel=e.tm.identifier(str(row['raw_fields'].get('building_name') or ''));assert not rawlabel.isdigit() or rawlabel==ns[2]
 exact=e.day(s['transaction_date'])==e.day(chosen['transaction_date']);tiers['exact_date' if exact else 'date_relaxed']+=1
 if exact:assert row['selected']['size']['matches'] and row['selected']['size']['basis']=='independent_training_sheet_unit'
 checks.append({'row_key':row['row_key'],'source_event_id':row['source_event_id'],'full_global_sale_pool':n,'valid_namespace_events':validn,'date_exact':exact,'same_event':True})
# If candidate units have baseline references at other prices, fetch these too before reuse audit.
candidate_uids={r['source_unit_id'] for r in rows};otherneeded={e.current_key(r) for r in baseline if r['source_unit_id'] in candidate_uids and e.current_key(r) not in selected_targets}
if otherneeded:
 for key,payload in pools.db.execute("SELECT json_extract(payload,'$.event_key'),payload FROM event WHERE family='sale'"):
  if 'sale:'+str(key) in otherneeded:selected_targets['sale:'+str(key)]=json.loads(payload)
refs=[(r,selected_targets[e.current_key(r)]) for r in baseline if e.current_key(r) in selected_targets]
temporary=[(r,{'status':'new_supported_inferred','selected':r['selected']}) for r in rows];reuse=e.veto(temporary,[],refs);assert all(x['status']=='new_supported_inferred' for r,x in temporary)
assert tiers=={'exact_date':158,'date_relaxed':13}
out={'check':'PASS','rows':len(rows),'unique_source_frames_replayed':len(cache),'date_tiers':dict(tiers),'full_global_price_pool_replay':True,'raw_identifiers_and_source_preserved':True,'original_contradiction_promotions':0,'reuse':reuse,'sqlite_total_changes':pools.db.total_changes,'checks':checks,'limitation':'Post-hoc namespace normalization has no blind accuracy estimate; 13 date-relaxed rows remain distinct review tier.'};(P/'verifier-namespace.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='checks'}))
