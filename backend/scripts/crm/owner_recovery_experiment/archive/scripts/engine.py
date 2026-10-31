"""Frozen offline recovery experiment. No contacts, remote calls, or persistent DB writes."""
from __future__ import annotations
import argparse, collections, hashlib, json, os, sqlite3, sys, time
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'frozen_backend'))
sys.path.insert(0,str(ROOT))
from app.crm import transaction_matching as tm
from app.crm.owner_matching_policy import SheetSizeEvidence, qualified, IDENTIFIER_FIELDS, SQM_TO_SQFT
CAUSES={'no_original_role_correct_full_identifier':13563,'named_location_label_absent_catalog':7844,'identified_property_no_sale_within_2_aed':6053,'original_address_codes_contradict':5341,'full_identifier_not_in_same_price_scoped_sales':3301}
RULES={'version':'five-group-offline-1','amount_tolerance_aed':'2','size_tolerance':'max(50 sqft, 2% source)','unknown_size_unit':'abstain unless >=10 independent training properties and >=95% exclusive votes per file/sheet, leave query unit out','missing_id':'qualified location + unique property + independently known/learned matching size OR exact date corroboration; date cannot remove competing properties','event_date':'unique exact event only after property established; unknown/within14day same-property competitor veto','contradictory_ids':'hypotheses remain tentative, original contradiction never removed','misidentified_property':'conflicting original child ID cannot be overridden by price/size/date','reuse':'contradictory source identifiers or source unit mapping to multiple properties veto supported claims','holdout':'deterministic connected target-property/source-unit split; rules frozen before holdout; learned evidence uses training partition only','weak_labels':'previous matches are weak labels, agreement is not ownership accuracy'}
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,default=str).encode()).hexdigest()
def save(name,v):
 (ROOT/name).write_text(json.dumps(v,indent=2,sort_keys=True,default=str)+'\n')
def read(name):return [json.loads(l) for l in (ROOT/name).open()]
def day(v):return tm._day(v)
def ek(r):return tm._event_key(r)
def prop(r):return tm.property_identity(r)
def current_key(r):return str(r.get('current_match',{}).get('selected_event_key') or r.get('current_match',{}).get('evidence',{}).get('selected_event_key') or '')
def current_live(r):return r.get('current_match',{}).get('status')=='matched' and current_key(r).startswith('sale:')
def raw_ids(s):return {k:str(v) for k,v in (s.get('original_identifiers') or {}).items() if tm.identifier(str(v or ''))}
def source_identity(s):
 ids=raw_ids(s);return tuple(tm.identifier(ids.get(k,'')) for k in IDENTIFIER_FIELDS)
def masked(s):
 z={**s,'original_identifiers':{}}
 for k in (*IDENTIFIER_FIELDS,'land_number','land_sub_number','municipality_number','municipality_sub_number'):z[k]=''
 z['raw_fields']={k:v for k,v in s.get('raw_fields',{}).items() if k not in {*IDENTIFIER_FIELDS,'land_number','land_sub_number','municipality_number','municipality_sub_number'}}
 z['source_unit_id']=s.get('source_unit_id');return z
class Pools:
 def __init__(self,path):
  self.db=sqlite3.connect('file:'+str(path)+'?mode=ro&immutable=1',uri=True);self.db.execute('PRAGMA query_only=ON');self.last=None;self.rows=[];self.rentals=0;self.calls=0;self.raw_rows=0
 def get(self,value):
  amount=tm.positive_decimal(value)
  if amount is None:return [],0
  if amount!=self.last:
   self.rows=[];self.rentals=0
   # SQLite REAL is retrieval only. Expand its endpoints; Decimal is authoritative.
   lo=float(amount-Decimal(2));hi=float(amount+Decimal(2));eps=max(abs(lo),abs(hi),1)*2e-15
   for family,payload in self.db.execute('SELECT family,payload FROM event WHERE amount BETWEEN ? AND ?',(lo-eps,hi+eps)):
    r=json.loads(payload)
    if not any(abs(v-amount)<=Decimal(2) for _,v in tm._amounts(r)):continue
    if family=='sale':self.rows.append(r)
    elif family=='rental':self.rentals+=1
   self.last=amount;self.calls+=1;self.raw_rows+=len(self.rows)
  return self.rows,self.rentals

def source_size(s,model):
 explicit=tm.positive_decimal(s.get('size_sqft')) if s.get('_declared_size_unit')!='unknown' else None
 if explicit:return explicit,{'basis':'explicit_or_current_established_sqft','value_sqft':str(explicit)}
 raw=tm.positive_decimal(s.get('size_unknown'))
 if raw:
  learned=model.infer(s)
  if learned:return raw*(SQM_TO_SQFT if learned['unit']=='sqm' else 1),{'basis':'independent_training_sheet_unit','raw':str(raw),**learned}
  return None,{'basis':'unknown_unit_abstention','raw':str(raw)}
 return None,{'basis':'no_source_size'}

def factor(s,r,model,size,size_evidence,mask=False):
 details=model.features(s,r)
 loc=details.get('location',{});ids=details.get('identifier',{})
 conflicts=list(loc.get('conflicts',[]))+list(ids.get('conflicts',[]))
 raw=raw_ids(s);observed=tm.identifier(str(r.get('unit_number') or ''))
 exact_fields=[k for k,v in raw.items() if tm.identifier(v)==observed]
 id_strength=ids.get('strength','none')
 role_rule=[]
 # Exact full codes retain source role provenance. A PropertyNo on an explicit
 # plot source is a defensible role reinterpretation, never suffix extraction.
 if tm._kind(s.get('property_type'))=='plot' and tm._kind(r.get('property_type'))=='plot' and 'property_number' in exact_fields:
  id_strength='full';role_rule=['property_number_plot_full_code_role_reinterpretation']
 location_ok=loc.get('strength') in {'building','parent'} and not loc.get('conflicts')
 named_labels=[str(s.get(k) or '') for k in ('building_name','project_name') if s.get(k)]
 generic_only=bool(named_labels) and all(tm.generic_building(v) or tm.identifier(v).isdigit() for v in named_labels)
 if generic_only and not s.get('area_name'):
  location_ok=False
  loc={**loc,'conflicts':sorted(set(loc.get('conflicts',[])+['generic_building_without_independent_named_context']))}
  conflicts.append('generic_building_without_independent_named_context')
 role_fields={'flat':('unit_number','property_number'),'villa':('unit_number','building_number'),'plot':('unit_number','plot_number','plot_pre_reg_number','property_number')}.get(tm._kind(r.get('property_type')),('unit_number',))
 role_supported=bool(set(exact_fields)&set(role_fields))
 id_ok=id_strength in {'full','unit'} and not ids.get('conflicts') and role_supported
 physical=not tm.physical_types_conflict(s.get('property_type'),r.get('property_type'))
 size_target=tm.positive_decimal(r.get('size_sqft'))
 size_ok=bool(size and size_target and tm.sizes_match(size,size_target))
 sd,rd=day(s.get('transaction_date')),day(r.get('transaction_date'))
 date_gap=abs((sd-rd).days) if sd and rd else None
 source_role_fields={'flat':('unit_number','property_number'),'villa':('unit_number','building_number'),'plot':('unit_number','plot_number','plot_pre_reg_number','property_number')}.get(tm._kind(s.get('property_type')) or tm._kind(r.get('property_type')),('unit_number',))
 known_parent_fields={a.get('source_field') for a in details.get('learned_aliases',[]) if a.get('kind')=='parent' and a.get('accepted')}
 known_raw_child=any(raw.get(k) for k in source_role_fields if k not in known_parent_fields)
 child_conflicts=[k for k in source_role_fields if k not in known_parent_fields and raw.get(k) and tm.identifier(raw[k])!=observed]
 if child_conflicts:
  id_ok=False
  conflicts.append('role_correct_original_child_conflict:'+','.join(child_conflicts))
 f={'event_key':ek(r),'property':list(prop(r)),'target':{k:r.get(k) for k in ('event_family','event_key','area_name','project_name','building_name','unit_number','property_type','amount_aed','sale_amount_aed','size_sqft','transaction_date')},'amount_gap_aed':str(min(abs(v-tm.positive_decimal(s.get('amount_aed'))) for _,v in tm._amounts(r))), 'location':loc,'learned_aliases':details.get('learned_aliases',[]),'identifier':{**ids,'exact_raw_fields':exact_fields,'role_rules':role_rule,'hypothesis':('preferred_full_child' if any(any(c.isalpha() for c in raw.get(k,'')) for k in exact_fields) else 'numeric_label' if exact_fields else 'unmatched_or_inferred')},'conflicts':conflicts,'physical_type_compatible':physical,'size':{**size_evidence,'target_sqft':str(size_target) if size_target else None,'matches':size_ok if size else None},'date':{'source':str(s.get('transaction_date')),'target':str(r.get('transaction_date')),'gap_days':date_gap,'exact':date_gap==0},'location_ok':location_ok,'id_ok':id_ok,'known_raw_child':known_raw_child,'candidate_complete':bool(all(prop(r)[1:]))}
 f['rank']=(int(location_ok),int(id_ok),int(physical),int(size_ok),int(date_gap==0),-date_gap if date_gap is not None else -100000)
 return f

def select(row,pool,rentals,aliases,sizes,mask=False):
 s={**row['source'],'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'raw_fields':row.get('raw_fields',{}),'_declared_size_unit':row.get('source_declared_size_unit')}
 if mask:s=masked(s)
 size,size_evidence=source_size(s,sizes)
 factors=[];extremes=[];hypotheses=collections.Counter();stages=collections.Counter();candidates=[]
 for target in pool:
  f=factor(s,target,aliases,size,size_evidence,mask)
  # All pool entries are evaluated. Only evidence-bearing alternatives are serialized.
  stages['amount_sale_events']+=1
  if f['location_ok']:stages['qualified_location_events']+=1
  if f['id_ok']:stages['full_or_unit_identifier_events']+=1
  if f['location_ok'] or f['id_ok']:factors.append(f)
  hypotheses[f['identifier']['hypothesis']]+=1
  # A bounded display of extreme candidates never limits the pool or supported selection.
  if len(extremes)<3 or f['rank']>extremes[-1]['rank']:
   extremes.append(f);extremes.sort(key=lambda z:z['rank'],reverse=True);extremes=extremes[:3]
  if f['location_ok'] and f['physical_type_compatible'] and f['candidate_complete']:
   candidates.append((target,f))
 reason='no_qualified_location_type_candidates';selected=None;rule=None;status='unresolved';survivors=[]
 if s.get('event_family')!='sale':candidates=[];reason='source_not_explicit_sale'
 if candidates:
  consistent=[x for x in candidates if x[1]['id_ok']]
  usable=consistent if consistent else [x for x in candidates if not x[1]['conflicts'] and (mask or not x[1]['known_raw_child'])]
  infer=not bool(consistent)
  reason='identifier_conflict_or_unmatched_original_child' if not usable else 'multiple_properties_or_events'
  if usable:
   if size and any(not tm.positive_decimal(t.get('size_sqft')) for t,f in usable):reason='unknown_target_size_prevents_uniqueness';usable=[]
   elif size:usable=[x for x in usable if x[1]['size']['matches']];reason='size_disagrees_all_candidates' if not usable else reason
   survivors=usable
   properties={prop(t) for t,f in usable}
   if len(properties)==1:
    chosen=usable[0] if len(usable)==1 else None
    if not chosen:
     target=tm.exact_date_event(s.get('transaction_date'),[t for t,f in usable])
     if target is not None:chosen=next(x for x in usable if x[0] is target)
    if chosen:
     target,f=chosen
     independent=bool(f['size']['matches'] or f['date']['exact'])
     if infer and not independent:reason='missing_identifier_price_location_only';selected=f;status='tentative';rule='unique_location_price_without_independent_corroboration'
     else:
      selected=f;status='new_supported_inferred';reason='unique_supported_candidate'
      rule=('inferred_id_location_'+('size' if f['size']['matches'] else 'exact_date')) if infer else ('exact_full_identifier_role_reinterpretation' if f['identifier']['role_rules'] else 'full_identifier_qualified_location')
    else:reason='ambiguous_transaction_or_close_date_competitor'
   elif len(properties)>1:reason='multiple_properties_date_cannot_disambiguate'
 if row.get('primary_cause')=='original_address_codes_contradict' and status=='new_supported_inferred' and not mask:
  status='tentative';reason='original_address_contradiction_retained';rule='preferred_full_child_hypothesis_requires_review'
 if selected is None and factors:
  selected=max(factors,key=lambda f:f['rank']);status='tentative';rule='aggressive_best_available_hypothesis'
 if selected is None and extremes:
  selected=extremes[0];status='tentative_high_risk';rule='extreme_price_size_date_without_qualified_location';reason='no_qualified_location_identifier_extreme_only'
 alternatives=sorted(factors,key=lambda f:f['rank'],reverse=True)
 for f in alternatives:f.pop('rank',None)
 if selected:selected.pop('rank',None)
 for f in extremes:f.pop('rank',None)
 return {'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'status':status,'rule':rule,'reason':reason,'selected':selected,'alternative_count':len(alternatives),'alternatives':alternatives[:8],'alternatives_display_truncated':max(0,len(alternatives)-8),'extreme_candidates':extremes,'identifier_hypotheses':dict(hypotheses),'stages':dict(stages),'same_amount_rental_event_count':rentals,'source_size':size_evidence,'candidate_pool_uncapped':True,'surviving_property_count':len({prop(t) for t,f in survivors})}

def dsu_split(pairs):
 parent={}
 def find(a):
  parent.setdefault(a,a)
  if parent[a]!=a:parent[a]=find(parent[a])
  return parent[a]
 def union(a,b):
  a,b=find(a),find(b)
  if a!=b:parent[max(a,b)]=min(a,b)
 for r,t in pairs:union('p:'+digest(prop(t)),'u:'+str(r['source_unit_id']))
 return {r['source_event_id']:('test' if int(digest(find('p:'+digest(prop(t))))[:8],16)%5==0 else 'train') for r,t in pairs}

def veto(results,all_rows,baseline_targets):
 source_props=collections.defaultdict(set);event_sources=collections.defaultdict(list)
 for r,t in baseline_targets:
  source_props[r['source_unit_id']].add(tuple(prop(t)));event_sources[ek(t)].append(r)
 for r,x in results:
  if x['status']=='new_supported_inferred' and x['selected']:
   source_props[r['source_unit_id']].add(tuple(x['selected']['property']));event_sources[x['selected']['event_key']].append(r)
 bad_events=set()
 for key,refs in event_sources.items():
  byunit={r['source_unit_id']:r for r in refs}
  ids={source_identity(r['source']) for r in byunit.values()}
  # Missing IDs contribute no conflict; two distinct explicit child codes do.
  for k in range(len(IDENTIFIER_FIELDS)):
   values={v[k] for v in ids if v[k]}
   if len(values)>1:bad_events.add(key)
  buildings={tm._location_number_markers(str(r['source'].get('building_name') or '')) for r in byunit.values()}
  buildings={tuple(sorted(v)) for v in buildings if v}
  if len(buildings)>1:bad_events.add(key)
 for r,x in results:
  if x['status']!='new_supported_inferred':continue
  why=[]
  if len(source_props[r['source_unit_id']])>1:why.append('source_unit_contradictory_property_mapping')
  if x['selected']['event_key'] in bad_events:why.append('reverse_event_reuse_contradictory_source_identifiers')
  if why:x.update(status='tentative',reason=';'.join(why),conflict_veto=why)
 return {'contradictory_source_units':sum(len(v)>1 for v in source_props.values()),'contradictory_reused_event_keys':len(bad_events)}

def run(args):
 os.umask(0o077);started=time.time()
 def fingerprints():
  paths=[ROOT/n for n in ('engine.py','aliases.py','rows.jsonl','baseline-matched.jsonl','frozen-code-hashes.json')]
  paths.extend(sorted((ROOT/'frozen_backend').rglob('*.py')))
  paths.extend(sorted((ROOT/'frozen_analytics').rglob('*.py')))
  paths.append(ROOT/'alias-dependency-manifest.json')
  values={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
  places_path=Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json')
  values[str(places_path)]=hashlib.sha256(places_path.read_bytes()).hexdigest()
  return values
 input_before=fingerprints()
 snapshot_before=(args.snapshot.stat().st_size,args.snapshot.stat().st_mtime_ns)
 save('engine-input-before.json',input_before)
 from aliases import AliasModel
 focus=read('rows.jsonl');baseline=read('baseline-matched.jsonl')
 assert collections.Counter(r['primary_cause'] for r in focus)==CAUSES
 save('engine-frozen-rules.json',{'rules':RULES,'sha256':digest(RULES),'frozen_before_holdout':True})
 db=Pools(args.snapshot);baseline_unique={r['source_event_id']:r for r in baseline};pairs=[];missing=0
 needed={current_key(r) for r in baseline};target_map={}
 for key,payload in db.db.execute("SELECT json_extract(payload,'$.event_key'),payload FROM event WHERE family='sale'"):
  if 'sale:'+str(key) in needed:target_map['sale:'+str(key)]=json.loads(payload)
 baseline_targets=[]
 for row in baseline:
  target=target_map.get(current_key(row))
  if target is None:missing+=1;continue
  baseline_targets.append((row,target))
  if row is baseline_unique[row['source_event_id']] and not row['current_match'].get('flags') and qualified(row['source'],target):pairs.append((row,target))
 split=dsu_split(pairs);train=[p for p in pairs if split[p[0]['source_event_id']]=='train'];test=[p for p in pairs if split[p[0]['source_event_id']]=='test']
 assert not {prop(t) for r,t in train}&{prop(t) for r,t in test}
 assert not {r['source_unit_id'] for r,t in train}&{r['source_unit_id'] for r,t in test}
 places=json.loads(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json').read_text())
 aliases=AliasModel(baseline_pairs=[{'source':{**r['source'],'source_event_id':r['source_event_id'],'source_unit_id':r['source_unit_id'],'raw_fields':r.get('raw_fields',{})},'target':t} for r,t in train],places=places)
 save('engine-alias-training-audit.json',aliases.audit())
 with (ROOT/'engine-training-pairs.jsonl').open('w') as out:
  for r,t in train:out.write(json.dumps({'source':r['source'],'raw_fields':r.get('raw_fields',{}),'source_unit_id':r['source_unit_id'],'source_event_id':r['source_event_id'],'target':t},sort_keys=True,default=str)+'\n')
 sizes=SheetSizeEvidence()
 for r,t in train:sizes.observe(r['source'],[(t,200,[])])
 save('engine-training-summary.json',{'weak_pairs':len(pairs),'train_pairs':len(train),'test_pairs':len(test),'baseline_unique_groups':len(baseline_unique),'baseline_missing_snapshot_target':missing,'baseline_target_rows':len(baseline_targets),'alias_training_rows':aliases.training_rows,'alias_rejected_training_rows':aliases.rejected_training_rows,'property_unit_split_disjoint':True,'rules_sha256':digest(RULES)})
 print(json.dumps({'checkpoint':'frozen_training','weak_pairs':len(pairs),'train':len(train),'holdout':len(test),'missing_targets':missing}),flush=True)
 grouped={}
 for r in focus:grouped.setdefault((r['source_event_id'],digest(r['source'])),r)
 computed={};results=[]
 for n,(key,row) in enumerate(sorted(grouped.items(),key=lambda p:Decimal(str(p[1]['source'].get('amount_aed') or 0))),1):
  pool,rentals=db.get(row['source'].get('amount_aed'))
  if current_live(row):x={'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'status':'already_live_recovered','rule':'current_backend_selected_sale','reason':'matched_before_offline_experiment','selected':None,'current_selected_event_key':current_key(row),'stages':{'amount_sale_events':len(pool)},'same_amount_rental_event_count':rentals,'candidate_pool_uncapped':True}
  else:x=select(row,pool,rentals,aliases,sizes)
  computed[key]=x
  if n%500==0:print(json.dumps({'checkpoint':'focus','groups':n,'total':len(grouped),'elapsed_seconds':round(time.time()-started)}),flush=True)
 for r in focus:
  x={**computed[(r['source_event_id'],digest(r['source']))]}
  if current_live(r):x.update(status='already_live_recovered',rule='current_backend_selected_sale',reason='matched_before_offline_experiment',current_selected_event_key=current_key(r))
  if r['primary_cause']=='original_address_codes_contradict' and x['status']=='new_supported_inferred':x.update(status='tentative',reason='original_address_contradiction_retained',rule='preferred_full_child_hypothesis_requires_review')
  results.append((r,x))
 conflicts=veto(results,[],baseline_targets)
 cats={c:{'rows':0,'statuses':collections.Counter(),'rules':collections.Counter(),'reasons':collections.Counter()} for c in CAUSES}
 with (ROOT/'results.jsonl').open('w') as out:
  for r,x in results:
   z={k:r.get(k) for k in ('row_key','filename','sheet','row','source_event_id','source_unit_id','original_category','primary_cause','source','raw_fields','current_match','current_status')};z.update(x);out.write(json.dumps(z,default=str,sort_keys=True)+'\n')
   c=cats[r['primary_cause']];c['rows']+=1;c['statuses'][x['status']]+=1;c['rules'][str(x.get('rule'))]+=1;c['reasons'][x['reason']]+=1
 hold=collections.defaultdict(collections.Counter);evaluation=[]
 evalpairs=[(r,t) for r,t in pairs if split[r['source_event_id']]=='test']
 for n,(r,t) in enumerate(sorted(evalpairs,key=lambda p:Decimal(str(p[0]['source'].get('amount_aed') or 0))),1):
  pool,rentals=db.get(r['source'].get('amount_aed'));x=select(r,pool,rentals,aliases,sizes,mask=True)
  evaluation.append((r,t,x))
  if n%500==0:print(json.dumps({'checkpoint':'holdout','groups':n,'total':len(evalpairs),'elapsed_seconds':round(time.time()-started)}),flush=True)
 holdout_veto=veto([({**r,'source':masked(r['source'])},x) for r,t,x in evaluation],[],train)
 with (ROOT/'engine-holdout.jsonl').open('w') as out:
  for r,t,x in evaluation:
   m=hold['property_unit_holdout'];m['weak_pairs']+=1;m[x['status']]+=1
   chosen=x.get('selected');supported=x['status']=='new_supported_inferred'
   if supported:
    m['selected']+=1;m['exact_event_agreement']+=int(chosen['event_key']==ek(t));m['same_property_agreement']+=int(tuple(chosen['property'])==prop(t));m['different_property_collision']+=int(tuple(chosen['property'])!=prop(t))
   out.write(json.dumps({'source_event_id':r['source_event_id'],'source_unit_id':r['source_unit_id'],'weak_event':ek(t),'weak_property':prop(t),'source':masked(r['source']),**x},default=str,sort_keys=True)+'\n')
 metrics={'check':'PASS','rows':len(focus),'source_events':len({r['source_event_id'] for r in focus}),'fixed_categories':cats,'statuses':dict(collections.Counter(x['status'] for r,x in results)),'not_supported_rows':sum(x['status'] not in {'new_supported_inferred','already_live_recovered'} for r,x in results),'holdout':dict(hold),'rules':RULES,'rules_sha256':digest(RULES),'conflicts':conflicts,'holdout_conflicts':holdout_veto,'pool_queries':db.calls,'queried_sale_event_records':db.raw_rows,'all_candidates_evaluated_no_pool_cap':True,'alternative_display_limit':8,'sqlite_total_changes':db.db.total_changes,'elapsed_seconds':round(time.time()-started),'limitations':['Weak-label agreement is not property-match precision or ownership accuracy.','Tentative/aggressive hypotheses are not recoveries.','Current recovered rows are not new offline gains.','Original contradictory codes remain explicit.']}
 assert db.db.total_changes==0
 assert metrics['statuses'].get('already_live_recovered',0)==sum(current_live(r) for r in focus)==8
 input_after=fingerprints();assert input_before==input_after,'Input/code changed during experiment'
 assert snapshot_before==(args.snapshot.stat().st_size,args.snapshot.stat().st_mtime_ns),'Snapshot changed during experiment'
 metrics['input_sha256']=input_after;metrics['input_hashes_unchanged']=True
 save('metrics.json',metrics);print(json.dumps({'check':'PASS','statuses':metrics['statuses'],'holdout':dict(hold),'elapsed_seconds':metrics['elapsed_seconds']}),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--snapshot',type=Path,default=Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite'));a=p.parse_args();run(a)
