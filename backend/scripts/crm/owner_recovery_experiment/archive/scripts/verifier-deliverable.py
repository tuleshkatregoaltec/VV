"""Read-only delivered workbook and ledger reconciliation."""
import json,zipfile,xml.etree.ElementTree as ET,collections,hashlib
from pathlib import Path
from openpyxl import load_workbook
P=Path('/tmp/vv-five-group-recovery-2026-10-29');OUT=Path('/mnt/c/Users/maan3/Downloads/owner-import-five-group-experiment-2026-10-29');path=OUT/'Five-Group-Recovery-Experiment.xlsx'
wb=load_workbook(path,read_only=True,data_only=False);sheetnames=wb.sheetnames;summary=list(wb['Summary'].iter_rows(values_only=True));total=summary[-1];assert total[0]=='TOTAL';assert [int(total[i]) for i in (1,2,3,4,8,9,10)]==[36102,8,0,2776,36094,33318,36102],total
counts=list(wb['Counting units'].iter_rows(values_only=True));wb.close()
with zipfile.ZipFile(path) as z:
 book=ET.fromstring(z.read('xl/workbook.xml'));ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'));relmap={r.attrib['Id']:r.attrib['Target'] for r in rels};selected=next(s for s in book.find('m:sheets',ns) if s.attrib['name']=='All 36102 rows');rid=selected.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'];target=relmap[rid];target=target.lstrip('/') if target.startswith('/') else 'xl/'+target;row_count=0;tail=b''
 with z.open(target) as f:
  for block in iter(lambda:f.read(1024*1024),b''):
   b=tail+block;row_count+=b.count(b'<row ');tail=b[-4:]
 assert row_count-1==36102
focus={r['row_key']:r for line in (P/'rows.jsonl').open() if (r:=json.loads(line))};combined={r['row_key']:r for line in (P/'combined-conditional-results.jsonl').open() if (r:=json.loads(line))};keys=set();statuses=collections.Counter();date_warnings=0;profiles=collections.Counter()
for line in (OUT/'row-results.jsonl').open():
 r=json.loads(line);key=r['row_key'];assert key not in keys and key in focus;keys.add(key);original=focus[key];assert all(r[k]==original[k] for k in ('source','raw_fields','primary_cause','original_category'));statuses[r['report_status']]+=1
 if r['report_status']=='extra_conditional_support':
  assert combined[key]['status']=='conditional_rule_c_candidate' and r['selected']['event_key']==combined[key]['selected']['event_key'];profiles[r['conditional_profile']['profile']]+=1;gap=(r['selected'].get('date') or {}).get('gap_days');date_warnings+=gap not in (None,0)
assert keys==set(focus) and statuses['already_live_recovered']==8 and statuses['extra_conditional_support']==2776 and statuses['new_conservative_support']==0
report=json.loads((OUT/'report-summary.json').read_text());assert dict(statuses)==report['totals'] and dict(profiles)==report['extra_conditional_rows_by_profile'];assert date_warnings==report['date_warning_supported_rows'].get('extra_conditional_support',0)
html=(OUT/'Read-Me-Examples.html').read_text();assert '36,102' in html and '2,776' in html and '33,318' in html
out={'check':'PASS','workbook_sheets':sheetnames,'workbook_original_rows':row_count-1,'summary_total_cells':total,'ledger_rows':len(keys),'ledger_statuses':dict(statuses),'profiles':dict(profiles),'date_warning_rows':date_warnings,'all_original_source_frames_preserved':True,'html_totals_match':True};(P/'verifier-deliverable.json').write_text(json.dumps(out,sort_keys=True,indent=2)+'\n');print(json.dumps(out,sort_keys=True))
