"""Contact-free, row-reconciled review artifacts. Reads final audited profiles only."""
import collections,hashlib,html,json,os,sys
from decimal import Decimal
from datetime import date
from pathlib import Path
from openpyxl import Workbook,load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
ROOT=Path(__file__).parent
CAUSES={
'no_original_role_correct_full_identifier':('No usable original unit/villa/plot identifier',13563),
'named_location_label_absent_catalog':('Location label not recognised in the captured catalogue',7844),
'identified_property_no_sale_within_2_aed':('Property found, but no sale within ±2 AED',6053),
'original_address_codes_contradict':('Conflicting address identifiers',5341),
'full_identifier_not_in_same_price_scoped_sales':('Same-price sales nearby, but the identifier differs',3301)}
RULES=[
('R1','Price stays strict','Every supported or conditional sale must be within AED 2, using decimal arithmetic. No price relaxation is counted as a recovery.'),
('R2','Use all sale candidates','Search the complete captured DXBI price pool. Rental counts are shown separately; a rental is not evidence that a named person bought a property. The snapshot may lack a real sale.'),
('R3','Normalise location with evidence','Reuse Analytics geography normalisation and catalogue bridges. Learn building/parent aliases from at least three different independently matched properties with 100% destination purity. Exclude the queried source and target property from their own alias support.'),
('R4','Preserve the whole identifier','Use the complete unit, villa or plot code in its proper role. A parent plot may identify a building, not a child apartment. Do not turn AFMU019B into villa 19B simply by chopping off the prefix.'),
('R5','Infer missing identifiers cautiously','For the conservative profile: qualified building or parent location, unique compatible property, and a matching independently interpreted size or exact date. A supplied contradictory child identifier is not treated as blank.'),
('R6','Interpret size independently','Use declared units when present. Otherwise learn sqm versus sqft per source sheet from at least 10 independent training properties, at least 95% exclusive votes, leaving the recognised queried source unit out. Convert sqm × 10.7639104167. Allow max(50 sqft, 2% of source size). Unknown units stay unknown; price alone never decides the unit.'),
('R7','Dates and competitors','The conservative profile uses dates to distinguish events after the property is established. It does not use date alone to discard other properties. Same-property close-date/unknown-date competitors can block selection.'),
('R8a / C1','Community with independent size','Explicit narrow community, price ±2, exact date, independently interpreted matching size, recognised compatible physical type, no original child-ID or precise-location conflict, and no competing compatible/unknown-size event within 14 days or with unknown date.'),
('R8b / C2','Try both size-unit interpretations','C1, but where the size unit cannot be learned independently, try BOTH sqft and sqm and require uniqueness across their union. The unit is candidate-dependent, not proven. Competing/unknown sizes under either interpretation block selection.'),
('R8c / C3','Broad source type is not a physical form','C2, but Residential, Building and Unit provide no certain physical-type discriminator. Preserve that raw label and flag the target-type assumption. Other plausible forms and unknown target types remain competitors; specific source-type contradictions still block selection.'),
('R8d / C4','Date-relaxed, unique across all history','C3, but dates may disagree ONLY when a single sale event survives the entire community + price ±2 + size pool across all captured dates. Every other plausible or unknown-size/type event blocks selection; dates cannot erase competitors. Candidate-dependent size/type and date discrepancies remain explicit assumptions.'),
('R8e / C5','Repair a demonstrated spreadsheet label sequence','Only repair a contiguous arithmetic label sequence supported by at least 10 independent training properties from the same sheet, all pointing to one community with the same name prefix. Exclude the queried source unit and candidate property from support, preserve the original label, and never override another valid community or a conflicting precise location. Then apply C3 exact-date or C4 all-history uniqueness separately. This is a conditional repair, not an overwrite.'),
('R9','Keep contradictions visible','Conflicting original address codes remain review cases unless independent evidence actually establishes their different roles. Price/size/date cannot silently overwrite a supplied identifier.'),
('R10','No double counting','One original row has one final reporting status. Several buyer/seller/owner rows can refer to one sale. Row, source-event and DXBI-property counts are distinct measures.'),
('R12 / Namespace','Read the whole structured villa code','A full code such as R3 Ruba-V-357 can map to Arabian Ranches 3 / Ruba / unit 357 only when the explicit named project and original numeric building label independently agree. Recognise III, lll and 3 in that master-project label. Do not apply this to arbitrary code suffixes. Exact-date and date-conflict candidates are separate conditional tiers.'),
('R11','Do not claim ownership proof','The experiment proposes transaction/property links. Agreement with earlier matches is a weak-label validation, not measured correctness or proof of the current owner. Owner names and live assignments are not modified.')]

def records(path):
 with Path(path).open() as f:
  for line in f:yield json.loads(line)
def filehash(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()
def js(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,default=str) if isinstance(v,(dict,list)) else v
def textcell(ws,v,color=None):
 c=WriteOnlyCell(ws,value=js(v));
 if isinstance(c.value,str):c.data_type='s'
 if color:c.fill=PatternFill('solid',fgColor=color)
 return c
class Sheet:
 def __init__(self,wb,name,headers,width=22):
  self.ws=wb.create_sheet(name);self.n=1;self.headers=headers;self.ws.freeze_panes='A2'
  for i,h in enumerate(headers,1):self.ws.column_dimensions[get_column_letter(i)].width=min(65,max(width,len(h)+2))
  cells=[]
  for h in headers:
   c=textcell(self.ws,h);c.font=Font(color='FFFFFF',bold=True);c.fill=PatternFill('solid',fgColor='234A62');cells.append(c)
  self.ws.append(cells)
 def add(self,values,color=None):self.ws.append([textcell(self.ws,v,color) for v in values]);self.n+=1
 def close(self):self.ws.auto_filter.ref=f'A1:{get_column_letter(len(self.headers))}{self.n}'

def summary_target(r):
 s=r.get('selected') or {};return s.get('target') or {},s

def gaps(r):
 t,z=summary_target(r);s=r.get('source') or {}
 if not z:return
 if z.get('amount_gap_aed') is None:
  a=t.get('sale_amount_aed') or t.get('amount_aed')
  if a is not None and s.get('amount_aed') is not None:z['amount_gap_aed']=str(abs(Decimal(str(a))-Decimal(str(s['amount_aed']))))
 if not z.get('date'):
  try:
   d=abs((date.fromisoformat(str(s['transaction_date'])[:10])-date.fromisoformat(str(t['transaction_date'])[:10])).days)
   z['date']={'source':s['transaction_date'],'target':t['transaction_date'],'gap_days':d,'exact':d==0}
  except (ValueError,KeyError,TypeError):pass
def describe(r):
 raw=r.get('raw_fields') or {};s=r.get('source') or {};t,p=summary_target(r)
 return {'source_file':r.get('filename'),'source_sheet':r.get('sheet'),'source_row':r.get('row'),'source_raw':raw,'source_normalized':s,'target':t,'rule':r.get('rule') or r.get('profile'),'reason':r.get('reason'),'status':r.get('report_status'),'original_cause':CAUSES[r['primary_cause']][0],'amount_gap_aed':p.get('amount_gap_aed'),'conflicts':p.get('conflicts',[]),'date':p.get('date'),'size':p.get('size') or r.get('size_evidence'),'alternatives':r.get('alternative_count'),'near_competitors':r.get('near_competitor_count'),'conditional_profile':r.get('conditional_profile'),'row_key':r['row_key']}

def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--main',required=True);p.add_argument('--community',required=True);p.add_argument('--out',required=True);args=p.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
 # Only conditional successes need to stay in memory; row reconciliation streams the large main ledger.
 community={r['row_key']:r for r in records(args.community) if r['status']=='conditional_rule_c_candidate'}
 diagnostics={r['row_key']:{k:r.get(k) for k in ['profile_reasons','community_repair_applied','latest_tested_reason']} for r in records(ROOT/'community-combined-results.jsonl')}
 wb=Workbook(write_only=True);intro=Sheet(wb,'Read me',['Topic','Explanation'],45)
 for a,b in [('Scope','Only the five original issue groups: 36,102 original rows. Other 74,225 named rows and 539 nameless rows are outside this experiment.'),('How to read statuses','Supported = passes conservative frozen rules. Conditional = extra recovery under the stronger joint-evidence profile. Tentative / extreme = hypothesis, not accepted match.'),('Original versus target','Original fields are preserved. DXBI fields are proposed links. A blank unit inferred from a match is not inserted into the original source.'),('Counts','The five issue groups are fixed starting buckets. A reduction means that row now passes a stated profile; it does not mean the original workbook suddenly contains the missing information.'),('Colours','Green = earlier/conservative support. Blue = conditional assumptions. Yellow = full identifier namespace agrees but date needs review. Orange = date needs review AND other assumptions such as repaired location or inferred identifier remain. Red = extreme candidate, not a recovery.'),('Privacy','This report contains property evidence, not owner names or contact details.'),('Accuracy','Historical accepted matches are weak labels. This is not a measured current-owner accuracy percentage.'),('Live backend','This experiment does not import, overwrite or publish the proposed links.')]:intro.add([a,b])
 summary=Sheet(wb,'Summary',['Original problem','Original rows','Already matched before experiment','New conservative support','Extra conditional support','Tentative candidates','Extreme candidates','No candidate','Remaining conservative only','Remaining including conditional','Total check'])
 rules=Sheet(wb,'Rules',['Rule','Name','Exact meaning'],35)
 for row in RULES:rules.add(row)
 headers=['Original problem','Result','File','Sheet','Original row','Source event ID','Source unit ID','Rule','Reason','Original area','Original master project','Original project','Original building','Original unit','Original building number','Original plot','Original property number','Original amount AED','Original date','Original size unknown','Original sqft','Original sqm','DXBI event key','DXBI area','DXBI project','DXBI building','DXBI unit','DXBI type','DXBI amount AED','DXBI date','DXBI sqft','Price gap AED','Date gap days','Size interpretation','Conflicts','Candidate sale count at price','Candidate rental count at price','Relevant alternatives count','Alternatives omitted from display','All original property fields','Normalized source','Match evidence','Row key']
 rows=Sheet(wb,'All 36102 rows',headers)
 exsheet=Sheet(wb,'Examples',headers)
 counter={c:collections.Counter() for c in CAUSES};examples={};events=collections.defaultdict(set);targets=collections.defaultdict(set);properties=collections.defaultdict(set);seen=set();datewarnings=collections.Counter();reasoncounts=collections.Counter();profilecounts=collections.Counter();filecounts=collections.defaultdict(collections.Counter);conditionaldates=collections.Counter()
 combined=out/'row-results.jsonl'
 with combined.open('w') as audit:
  for r in records(args.main):
   assert r['row_key'] not in seen;seen.add(r['row_key']);base=r['status'];c=community.get(r['row_key'])
   if base=='already_live_recovered':status='already_live_recovered'
   elif base=='new_supported_inferred':status='new_conservative_support'
   elif c:
    status='extra_conditional_support';r={**r,'conservative_status':base,'conservative_reason':r['reason'],'selected':c.get('selected'),'rule':c.get('profile','conditional community profile'),'conditional_profile':c,'reason':c['reason'],'community_evidence':c.get('community_evidence'),'size_evidence':c.get('size_evidence'),'near_competitor_count':c.get('near_competitor_count')}
   else:status=base
   r['conditional_profile_diagnostics']=diagnostics[r['row_key']]
   if status not in ('already_live_recovered','new_conservative_support','extra_conditional_support') and diagnostics[r['row_key']].get('community_repair_applied'):
    r['original_engine_reason']=r['reason'];r['reason']='after_location_repair: '+str(diagnostics[r['row_key']].get('latest_tested_reason'));r['displayed_extreme_candidate_from_original_profile']=True
   if status=='extra_conditional_support':profilecounts[c.get('profile','unspecified')]+=1
   gaps(r);r['report_status']=status;counter[r['primary_cause']][status]+=1;filecounts[r['filename']][status]+=1;reasoncounts[(r['primary_cause'],status,r['reason'])]+=1;events[status].add(r['source_event_id']);t,z=summary_target(r)
   if z.get('event_key'):targets[status].add(z['event_key'])
   if z.get('property'):properties[status].add(js(z['property']))
   gap=(z.get('date') or {}).get('gap_days')
   if status=='extra_conditional_support':conditionaldates['exact_date' if gap==0 else 'date_unknown' if gap is None else 'date_differs']+=1
   color='E8F3E8' if status in ('new_conservative_support','already_live_recovered') else 'E8EFFA' if status=='extra_conditional_support' else 'FCE8E6' if status=='tentative_high_risk' else None
   if status in ('new_conservative_support','extra_conditional_support') and gap!=0:color='FFF2CC' if (r.get('conditional_profile') or {}).get('profile')=='conditional_namespace_date_relaxed' or status=='new_conservative_support' else 'FCE4D6';datewarnings[status]+=1
   raw=r.get('raw_fields',{});s=r.get('source',{})
   values=[CAUSES[r['primary_cause']][0],status,r['filename'],r['sheet'],r['row'],r['source_event_id'],r['source_unit_id'],r.get('rule'),r['reason'],*[raw.get(k) for k in ['area_name','master_project','project_name','building_name','unit_number','building_number','plot_number','property_number','transaction_price_aed','transaction_date','size_unknown','size_sqft','size_sqm']],z.get('event_key') or r.get('current_selected_event_key'),*[t.get(k) for k in ['area_name','project_name','building_name','unit_number','property_type']],t.get('sale_amount_aed') or t.get('amount_aed'),t.get('transaction_date'),t.get('size_sqft'),z.get('amount_gap_aed'),gap,z.get('size') or r.get('size_evidence') or r.get('source_size'),z.get('conflicts'),r.get('stages',{}).get('amount_sale_events'),r.get('same_amount_rental_event_count'),r.get('alternative_count'),r.get('alternatives_display_truncated'),raw,s,{'selected':z,'conditional_profile':r.get('conditional_profile'),'all_profile_diagnostics':r.get('conditional_profile_diagnostics'),'original_engine_reason':r.get('original_engine_reason')},r['row_key']]
   assert len(values)==len(headers),(len(values),len(headers));rows.add(values,color)
   key=(r['primary_cause'],status,r.get('rule'),r['reason'])
   if key not in examples:examples[key]=(describe(r),values,color)
   audit.write(js(r)+'\n')
 assert len(seen)==36102
 totals=collections.Counter()
 for cause,(label,n) in CAUSES.items():
  c=counter[cause];assert sum(c.values())==n,(cause,c);totals.update(c)
  summary.add([label,n,c['already_live_recovered'],c['new_conservative_support'],c['extra_conditional_support'],c['tentative'],c['tentative_high_risk'],c['unresolved'],n-c['already_live_recovered']-c['new_conservative_support'],n-c['already_live_recovered']-c['new_conservative_support']-c['extra_conditional_support'],sum(c.values())])
 summary.add(['TOTAL',36102,totals['already_live_recovered'],totals['new_conservative_support'],totals['extra_conditional_support'],totals['tentative'],totals['tentative_high_risk'],totals['unresolved'],36102-totals['already_live_recovered']-totals['new_conservative_support'],36102-totals['already_live_recovered']-totals['new_conservative_support']-totals['extra_conditional_support'],sum(totals.values())])
 order={'new_conservative_support':0,'extra_conditional_support':1,'already_live_recovered':2,'tentative':3,'tentative_high_risk':4,'unresolved':5}
 selected=sorted(examples.values(),key=lambda x:(order[x[0]['status']],x[0]['original_cause'],str(x[0]['rule'])))
 for d,v,color in selected:exsheet.add(v,color)
 (out/'examples.json').write_text(json.dumps([d for d,v,col in selected],indent=2,ensure_ascii=False))
 counts=Sheet(wb,'Counting units',['Status','Original rows','Distinct source events (overlap across statuses)','Distinct proposed DXBI events','Distinct proposed DXBI properties'])
 for st,n in totals.items():counts.add([st,n,len(events[st]),len(targets[st]),len(properties[st])])
 counts.add(['Unique source events across ALL statuses',36102,len(set().union(*events.values())),None,None])
 boundary=Sheet(wb,'Rejected price examples',['File','Sheet','Original row','Original property fields','Previously linked property (may be wrong)','Source price AED','Closest history price AED','Difference AED','Sale history count','Reference DXBI sale','Why rejected'])
 for r in records(ROOT/'price-boundary.jsonl'):boundary.add([r['filename'],r['sheet'],r['row'],r['raw_fields'],r['previously_linked_property'],r['source_amount_aed'],r['closest_history_amount_aed'],r['absolute_price_difference_aed'],r['history_sale_count'],r['reference_sale'],r['explanation']])
 reasons=Sheet(wb,'Remaining reasons',['Original problem','Status','Reason','Rows'])
 for (cause,st,reason),n in reasoncounts.most_common():reasons.add([CAUSES[cause][0],st,reason,n])
 profiles=Sheet(wb,'Conditional assumptions',['Profile','Extra rows after conservative priority','Interpretation'])
 for pr,n in profilecounts.items():profiles.add([pr,n,'Exploratory conditional links; inspect C1-C4 rules and per-row assumption evidence.'])
 files=Sheet(wb,'By file',['File','Focus rows','Already matched','New conservative','Extra conditional','Remaining'])
 for fn,c in filecounts.items():files.add([fn,sum(c.values()),c['already_live_recovered'],c['new_conservative_support'],c['extra_conditional_support'],sum(c.values())-c['already_live_recovered']-c['new_conservative_support']-c['extra_conditional_support']])
 validation=Sheet(wb,'Validation',['Profile','Weak labels','Evaluated','Excluded encoded location IDs','Selected','Same event','Same property','Different property','Candidate-dependent size selected','Caution'])
 vr=json.loads((ROOT/'validation-report.json').read_text())
 for v in vr['profiles']:validation.add([v[k] for k in ['profile','weak_pairs','evaluated','excluded_location_leakage','selected','same_event','same_property','different_property','candidate_dependent_size_selected','caution']])
 disagreements=Sheet(wb,'Validation disagreements',['Scope','Profile','Original reference row','Previous accepted property','Previous accepted event','New proposed event and property','Assumptions','Size evidence','Date evidence'])
 for v in vr['different_property_examples']:disagreements.add(['Validation only: identifiers deliberately hidden; outside recovery count',v['profile'],v['original'],v['previous_accepted_property'],v['previous_accepted_event'],v['proposed'],v['assumption_tier'],v['size_evidence'],v['date_evidence']],'FCE8E6')
 for sh in [intro,summary,rules,rows,exsheet,counts,boundary,reasons,profiles,files,validation,disagreements]:sh.close()
 path=out/'Five-Group-Recovery-Experiment.xlsx';wb.save(path)
 check=load_workbook(path,read_only=True,data_only=False);actual=sum(1 for _ in check['All 36102 rows'].iter_rows())-1;assert actual==36102;check.close()
 result={'fixed_rows':36102,'categories':{k:dict(v) for k,v in counter.items()},'totals':dict(totals),'row_total_check':sum(totals.values()),'unique_source_events':len(set().union(*events.values())),'by_file':{fn:dict(v) for fn,v in filecounts.items()},'extra_conditional_rows_by_profile':dict(profilecounts),'conditional_date_status':dict(conditionaldates),'date_warning_supported_rows':dict(datewarnings),'remaining_reasons':[{'cause':c,'status':st,'reason':why,'rows':n} for (c,st,why),n in reasoncounts.most_common()],'examples':len(selected),'workbook_reopened_rows':actual,'main_input_sha256':filehash(args.main),'community_input_sha256':filehash(args.community)}
 (out/'report-summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
