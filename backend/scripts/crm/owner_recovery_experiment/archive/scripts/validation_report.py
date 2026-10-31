import json,collections
from pathlib import Path
R=Path(__file__).parent
names=['community-summary.json','community-c2-summary.json','community-c3-summary.json','community-c4-summary.json','community-c5-exact-summary.json','community-c5-history-summary.json']
profiles=[('Conservative','metrics.json')]+[(Path(name).stem,name) for name in names if (R/name).exists()]
rows=[]
for title,name in profiles:
 d=json.loads((R/name).read_text());h=d.get('holdout') or {}
 if 'property_unit_holdout' in h:h=h['property_unit_holdout']
 if not h:continue
 rows.append({'profile':d.get('profile',title),'summary_file':name,'weak_pairs':h.get('weak_pairs'),'evaluated':h.get('evaluated_masked_pairs',h.get('weak_pairs')),'excluded_location_leakage':h.get('excluded_location_identifier_leakage',0),'selected':h.get('selected',0),'same_event':h.get('same_event_agreement',h.get('exact_event_agreement',0)),'same_property':h.get('same_property_agreement',0),'different_property':h.get('different_property_collision',0),'candidate_dependent_size_selected':h.get('candidate_dependent_size_selected',0),'caution':'Previously accepted links are weak labels, not independently verified truth. Exploratory profiles reuse the same holdout.'})
collisions=[]
for path in [R/name.replace('-summary.json','-holdout.jsonl') for name in names if (R/name.replace('-summary.json','-holdout.jsonl')).exists()]:
 for l in path.open():
  r=json.loads(l);s=r.get('selected') or {}
  if s and r.get('weak_property') and s.get('property')!=r['weak_property'] and str(r['status']).startswith('conditional'):
   collisions.append({'profile':r['profile'],'source_event_id':r['source_event_id'],'row_key':r.get('row_key'),'previous_accepted_property':r['weak_property'],'previous_accepted_event':r.get('weak_event'),'proposed':s,'assumption_tier':r.get('assumption_tier'),'size_evidence':r.get('size_evidence'),'date_evidence':r.get('date_evidence'),'validation_only_identifiers_hidden':True})
need={x['source_event_id'] for x in collisions};original={}
for l in (R/'baseline-matched.jsonl').open():
 r=json.loads(l)
 if r['source_event_id'] in need and r['source_event_id'] not in original:original[r['source_event_id']]={k:r.get(k) for k in ['filename','sheet','row','raw_fields','source']}
for x in collisions:x['original']=original.get(x['source_event_id'])
(R/'validation-report.json').write_text(json.dumps({'profiles':rows,'different_property_examples':collisions,'unique_disagreement_source_events':len({v['source_event_id'] for v in collisions}),'note':'The same weak-label case can appear in multiple profiles; do not add disagreement counts across profiles.'},indent=2));print(json.dumps({'profiles':len(rows),'different_property_examples':len(collisions)}))
