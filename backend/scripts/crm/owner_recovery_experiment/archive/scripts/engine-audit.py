"""Check complete row accounting and recovery invariants from final artifacts."""
import collections, hashlib, json
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parent
focus={json.loads(l)['row_key']:json.loads(l) for l in (ROOT/'rows.jsonl').open()}
seen=set();status=collections.Counter();categories=collections.Counter();events=collections.defaultdict(set);selected_events=collections.defaultdict(set);properties=collections.defaultdict(set)
for line in (ROOT/'results.jsonl').open():
 r=json.loads(line);key=r['row_key'];assert key in focus and key not in seen;seen.add(key)
 assert r['primary_cause']==focus[key]['primary_cause'];assert r['source']==focus[key]['source'];assert r['raw_fields']==focus[key]['raw_fields']
 c=r['primary_cause'];tier=r['status'];categories[c]+=1;status[tier]+=1;events[tier].add(r['source_event_id'])
 if tier=='new_supported_inferred':
  t=r['selected'];assert c!='original_address_codes_contradict';assert r['source']['event_family']=='sale';assert not t['conflicts'];assert t['location_ok'];assert t['physical_type_compatible']
  assert abs(Decimal(str(t['target']['amount_aed']))-Decimal(str(r['source']['amount_aed'])))<=Decimal(2)
  if r['rule'].startswith('inferred_id_'):assert t['size']['matches'] or t['date']['exact'];assert not t['known_raw_child']
  selected_events[tier].add(t['event_key']);properties[tier].add(tuple(t['property']))
 assert r['candidate_pool_uncapped']
assert seen==set(focus) and len(seen)==36102 and status['already_live_recovered']==8
metrics=json.loads((ROOT/'metrics.json').read_text());assert dict(status)==metrics['statuses'];assert dict(categories)=={k:v['rows'] for k,v in metrics['fixed_categories'].items()}
assert metrics['sqlite_total_changes']==0 and metrics['input_hashes_unchanged']
if 'safety_filter' in metrics:assert hashlib.sha256((ROOT/'engine-safety.py').read_bytes()).hexdigest()==metrics['safety_filter'].get('optimization_code_sha256',metrics['safety_filter']['safety_code_sha256'])
for name,expected in metrics['input_sha256'].items():
 path=Path(name) if name.startswith('/') else ROOT/name
 assert hashlib.sha256(path.read_bytes()).hexdigest()==expected,name
h=collections.Counter()
for line in (ROOT/'engine-holdout.jsonl').open():
 r=json.loads(line);h['weak_pairs']+=1
 assert not r['source']['original_identifiers']
 for field in ('unit_number','building_number','property_number','plot_number','plot_pre_reg_number','land_number','municipality_number'):assert not r['source'].get(field),field
 if r['status']=='new_supported_inferred':
  h['selected']+=1;h['exact_event_agreement']+=r['selected']['event_key']==r['weak_event'];h['same_property_agreement']+=r['selected']['property']==r['weak_property'];h['different_property_collision']+=r['selected']['property']!=r['weak_property']
for k,v in h.items():assert v==metrics['holdout']['property_unit_holdout'][k],k
summary={'check':'PASS','rows':len(seen),'categories':dict(categories),'statuses':dict(status),'source_events_per_status':{k:len(v) for k,v in events.items()},'source_event_status_overlaps':{a+' / '+b:len(events[a]&events[b]) for a in events for b in events if a<b and events[a]&events[b]},'new_unique_selected_events':len(selected_events['new_supported_inferred']),'new_unique_properties':len(properties['new_supported_inferred']),'holdout_recomputed':dict(h),'unchanged_input_hashes':len(metrics['input_sha256'])}
(ROOT/'engine-audit.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(json.dumps(summary,sort_keys=True))
