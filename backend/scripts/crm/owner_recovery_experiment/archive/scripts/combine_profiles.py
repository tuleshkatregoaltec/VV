"""Combine independent conditional profiles, retaining all conflicts and baseline vetoes."""
import collections,json,sys
from pathlib import Path
R=Path(__file__).parent;sys.path.insert(0,str(R));import engine as e

def load(path):
 with Path(path).open() as f:
  for l in f:yield json.loads(l)
focus={r['row_key']:r for r in load(R/'rows.jsonl')}
community={r['row_key']:r for r in load(R/'community-combined-results.jsonl') if str(r['status']).startswith('conditional')}
namespace={r['row_key']:r for r in load(R/'engine-namespace-delivery.jsonl')}
proposals=[];report={};disagreements=[]
for key in focus:
 c=community.get(key);ns=namespace.get(key);options=[x for x in (c,ns) if x]
 if not options:continue
 if c and ns and (c['selected']['event_key']!=ns['selected']['event_key'] or c['selected']['property']!=ns['selected']['property']):
  disagreements.append({'row_key':key,'community':c,'namespace':ns});report[key]={'row_key':key,'status':'unresolved','reason':'independent_profile_target_disagreement','alternatives':options};continue
 if ns and ns['status']=='conditional_namespace_exact':x={**ns,'profile':'conditional_namespace_exact'}
 elif c:x={**c}
 else:x={**ns,'profile':'conditional_namespace_date_relaxed'}
 x['reason']=x.get('reason') or ('full_original_code_and_named_project_identify_namespace' if ns and x.get('profile','').startswith('conditional_namespace') else 'conditional_profile_candidate');x['original_profile_status']=x['status'];x['status']='new_supported_inferred';x['row_key']=key;proposals.append((focus[key],x));report[key]=x
baseline=list(load(R/'baseline-matched.jsonl'));needed={e.current_key(r) for r in baseline};targets={};pools=e.Pools(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite'))
for key,payload in pools.db.execute("SELECT json_extract(payload,'$.event_key'),payload FROM event WHERE family='sale'"):
 if 'sale:'+str(key) in needed:targets['sale:'+str(key)]=json.loads(payload)
assert needed==targets.keys()
veto=e.veto(proposals,[],[(r,targets[e.current_key(r)]) for r in baseline]);demotions=[]
for row,x in proposals:
 if x['status']=='new_supported_inferred':x['status']='conditional_rule_c_candidate'
 else:x['status']='unresolved';demotions.append({'row_key':row['row_key'],'reason':x['reason'],'profile':x['profile']})
counts=collections.Counter();bycause=collections.defaultdict(collections.Counter);profilecounts=collections.Counter()
with (R/'combined-conditional-results.jsonl').open('w') as f:
 for key,row in focus.items():
  x=report.get(key) or {'row_key':key,'status':'unresolved','reason':'no_additional_conditional_profile_candidate','selected':None}
  x={**{k:row.get(k) for k in ['row_key','source_event_id','source_unit_id','primary_cause']},**x}
  f.write(json.dumps(x,sort_keys=True,default=str)+'\n');counts[x['status']]+=1;bycause[row['primary_cause']][x['status']]+=1
  if x['status']=='conditional_rule_c_candidate':profilecounts[x['profile']]+=1
summary={'check':'PASS','rows':len(focus),'statuses':dict(counts),'categories':{k:dict(v) for k,v in bycause.items()},'profiles':dict(profilecounts),'same_row_target_disagreements':len(disagreements),'combined_global_veto_demotions':demotions,'global_veto':veto,'baseline_reference_rows':len(baseline),'snapshot_writes':pools.db.total_changes}
(R/'combined-conditional-summary.json').write_text(json.dumps(summary,indent=2));(R/'combined-profile-disagreements.json').write_text(json.dumps(disagreements,indent=2));assert len(focus)==36102 and pools.db.total_changes==0;print(json.dumps(summary))
