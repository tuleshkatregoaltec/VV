"""Read-only rejected references: never changes a match or widens +/-2 AED."""
import collections,json,sqlite3,sys
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'frozen_backend'))
from app.crm import transaction_matching as tm
rows=[json.loads(l) for l in (ROOT/'rows.jsonl').open()]
rows=[r for r in rows if r['primary_cause']=='identified_property_no_sale_within_2_aed']
diag={r['source_event_id']:r for l in Path('/tmp/vv-owner-review-root-causes-2026-10-29/event-diagnostics.jsonl').open() if (r:=json.loads(l)).get('supported_property_identity')}
db=sqlite3.connect('file:/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite?mode=ro&immutable=1',uri=True);db.execute('pragma query_only=on')
cache={};counts=collections.Counter();out=[]
for row in rows:
 d=diag.get(row['source_event_id']);identity=d.get('supported_property_identity') if d else None
 if not identity:
  counts['no_previous_property_identity']+=1;continue
 key=json.dumps(identity,separators=(',',':'))
 if key not in cache:
  cache[key]=[json.loads(p) for (p,) in db.execute("SELECT payload FROM event WHERE family='sale' AND identity=?",(key,))]
 price=tm.positive_decimal(row['source']['amount_aed'])
 events=cache[key]
 if not events:counts['no_sale_in_previously_linked_property_history']+=1;continue
 choices=[]
 for e in events:
  values=[(abs(p-price),p) for _,p in tm._amounts(e)]
  if values:
   delta,value=min(values);choices.append((delta,tm._event_key(e),value,e))
 if not choices:counts['no_positive_history_amount']+=1;continue
 delta,_,value,e=min(choices,key=lambda x:(x[0],x[1]))
 bucket='within_2' if delta<=2 else 'over_2_to_50' if delta<=50 else 'over_50_to_1000' if delta<=1000 else 'over_1000_to_10000' if delta<=10000 else 'over_10000'
 counts[bucket]+=1
 out.append({'row_key':row['row_key'],'filename':row['filename'],'sheet':row['sheet'],'row':row['row'],'source_event_id':row['source_event_id'],'primary_cause':row['primary_cause'],'source':row['source'],'raw_fields':row['raw_fields'],'previously_linked_property':identity,'history_sale_count':len(events),'status':'rejected_price_boundary_reference' if delta>2 else 'previous_history_within_tolerance_needs_audit','source_amount_aed':str(price),'closest_history_amount_aed':str(value),'absolute_price_difference_aed':str(delta),'bucket':bucket,'reference_sale':{k:e.get(k) for k in ['event_key','sale_key','event_family','unit_number','building_name','project_name','area_name','property_type','size_sqft','transaction_date','sale_amount_aed','detail_url']},'explanation':'Closest recorded sale on a previously linked property; this is not a proposed successful match. A previous property link may itself be wrong.'})
with (ROOT/'price-boundary.jsonl').open('w') as f:
 for r in out:f.write(json.dumps(r,sort_keys=True,default=str)+'\n')
(ROOT/'price-boundary-summary.json').write_text(json.dumps({'fixed_cohort_rows':len(rows),'covered_rows':len(out),'counts':dict(counts),'price_tolerance_unchanged':'2 AED','sqlite_total_changes':db.total_changes},indent=2))
print(json.dumps({'fixed_cohort_rows':len(rows),'covered_rows':len(out),'counts':dict(counts),'sqlite_total_changes':db.total_changes}))
