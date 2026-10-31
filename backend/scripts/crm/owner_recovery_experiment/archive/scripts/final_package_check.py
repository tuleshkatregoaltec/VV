import collections,gzip,hashlib,json,shutil
from decimal import Decimal
from pathlib import Path
R=Path(__file__).parent;O=Path('/mnt/c/Users/maan3/Downloads/owner-import-five-group-experiment-2026-10-29');A=O/'Audit'
count=0;days=[];prices=[]
with gzip.open(A/'row-results.jsonl.gz','rt') as f:
 for line in f:
  r=json.loads(line);count+=1
  if r['report_status']=='extra_conditional_support':
   days.append(r['selected']['date']['gap_days']);prices.append(Decimal(r['selected']['amount_gap_aed']))
e=json.loads((R/'actual-rule-extents.json').read_text());assert count==36102 and len(days)==2776 and sum(d==0 for d in days)==1942 and sum(d>0 for d in days)==834 and max(days)==e['date_gap_max_days']==2765 and max(prices)==Decimal(e['price_gap_max_aed'])==1
shutil.copy2(R/'actual-rule-extents.json',A/'actual-rule-extents.json');shutil.copy2(R/'explanation.py',A/'experiment-code/explanation.py')
p=O/'START-HERE.txt';s=p.read_text();s+='\nActual relaxation: maximum observed price gap AED 1 (rule allows AED 2). Date-relaxed proposals have no maximum date cutoff; the most extreme observed gap is 2,765 days. 511 rows exceed one year, 471 exceed two years and 258 exceed five years; these thresholds overlap.\n';p.write_text(s)
manifest=json.loads((O/'artifact-manifest.json').read_text())
for rel in ['Read-Me-Examples.html','START-HERE.txt','Audit/actual-rule-extents.json','Audit/experiment-code/explanation.py']:
 p=O/rel;manifest[rel]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
(O/'artifact-manifest.json').write_text(json.dumps(manifest,indent=2));result={'check':'PASS','gzip_rows':count,'conditional_rows':len(days),'exact_date':sum(d==0 for d in days),'date_differs':sum(d>0 for d in days),'max_gap_days':max(days),'max_price_gap_aed':str(max(prices))};(R/'final-package-check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));print(json.dumps({p.name:p.stat().st_size for p in O.iterdir() if p.is_file()}))
