import collections,json,re
from pathlib import Path
R=Path(__file__).parent;rows=[]
for l in (R/'all-rows.jsonl').open():
 r=json.loads(l)
 if 'Damac' not in r['filename']:continue
 v=str(r.get('raw_fields',{}).get('master_project') or '')
 m=re.fullmatch(r'DAMAC\s+HILLS\s+(\d+)',v,re.I)
 if m:rows.append({'row_key':r['row_key'],'filename':r['filename'],'sheet':r['sheet'],'row':r['row'],'label':v,'suffix':int(m[1]),'primary_cause':r['primary_cause'],'source_event_id':r['source_event_id']})
byoffset=collections.defaultdict(list)
for r in rows:
 if r['suffix']>2:byoffset[(r['sheet'],r['row']-r['suffix'])].append(r)
groups=[]
for (sheet,offset),rs in sorted(byoffset.items(),key=lambda kv:-len(kv[1])):
 rs.sort(key=lambda r:r['row']);n=len(rs)
 groups.append({'sheet':sheet,'row_minus_label_suffix':offset,'rows':n,'first':rs[0],'last':rs[-1],'all_adjacent_pairs_same_slope':all(b['suffix']-a['suffix']==b['row']-a['row'] for a,b in zip(rs,rs[1:])),'focus_rows':sum(r['primary_cause'] is not None for r in rs),'focus_causes':dict(collections.Counter(r['primary_cause'] for r in rs if r['primary_cause'])),'example_rows':rs[:4]+rs[-4:]})
result={'file':'Damac hills 2 April 2024.xlsx','all_named_rows_with_family_label':len(rows),'normal_label_2_rows':sum(r['suffix']==2 for r in rows),'numbered_suffix_over_2_rows':sum(r['suffix']>2 for r in rows),'groups':groups,'interpretation':'Exact arithmetic progression is evidence of a damaged label sequence, not proof of intended community. Independent training-sheet community evidence is required for proposed repair.'}
(R/'label-sequence-evidence.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
