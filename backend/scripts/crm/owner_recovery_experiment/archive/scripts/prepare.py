import asyncio, collections, hashlib, json, os, shutil, sys
from pathlib import Path
ROOT=Path(__file__).parent
REPO=Path('/home/maan3/vv/VV-git')
os.umask(0o077)
code={}
for p in (REPO/'backend/app').rglob('*.py'):
 target=ROOT/'frozen_backend/app'/p.relative_to(REPO/'backend/app');target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():shutil.copy2(p,target)
 code[str(p.relative_to(REPO))]=hashlib.sha256(target.read_bytes()).hexdigest()
(ROOT/'frozen-code-hashes.json').write_text(json.dumps(code,indent=2))
sys.path.insert(0,str(ROOT/'frozen_backend'))
from app.config import settings
from app.crm.owner_assessment import _candidate
from app.crm.import_events import source_size_unit
from app.crm.ownership import _amount_match_source
import asyncpg
CAUSES={'no_original_role_correct_full_identifier':13563,'named_location_label_absent_catalog':7844,'identified_property_no_sale_within_2_aed':6053,'original_address_codes_contradict':5341,'full_identifier_not_in_same_price_scoped_sales':3301}
review=[json.loads(line) for line in Path('/tmp/vv-owner-review-root-causes-2026-10-29/review-row-ledger.jsonl').open()]
fixed={ (r['filename'],r['sheet'],r['row']):r for r in review if r['primary_cause'] in CAUSES }
assert dict(collections.Counter(r['primary_cause'] for r in fixed.values()))==CAUSES
ledger={ (r['filename'],r['sheet'],r['row']):r for line in Path('/tmp/vv-owner-ui-reconciliation-2026-10-29/row-ledger.jsonl').open() if (r:=json.loads(line))['category']!='no_name'}
publication=json.loads(Path('/tmp/vv-owner-backend-integration-2026-10-29/publication.json').read_text())
ids={r['import_id']:f for f,r in publication['files'].items()}
EVIDENCE=('source_fields','original_property_fields','source_identifiers','original_identifiers','source_registry_location_resolution','source_area_field','address_recovery','inferred_file_context','source_filename','source_file_sha256','source_import_scope','source_size_unit','inferred_size_unit','learned_size_units','source_size_unit_inference','raw_source_fields','amount_first_match','owner_match_policy','property_identity_resolution','resolver_version')
SAFE_FIELDS={'area_name','project_name','master_project','building_name','building_number','property_number','plot_number','plot_pre_reg_number','unit_number','land_number','land_sub_number','municipality_number','municipality_sub_number','property_type','transaction_price_aed','transaction_date','size_sqft','size_sqm','size_unknown','area_sqft','plot_area_sqft','total_area_sqft','procedure_type','party_role'}
def safe_source_fields(value):
 return {k:v for k,v in (value or {}).items() if k in SAFE_FIELDS}
def dump_line(stream,obj):stream.write(json.dumps(obj,sort_keys=True,default=str)+'\n')
async def main():
 connection=await asyncpg.connect(str(settings.POSTGRES_URL).replace('postgresql+asyncpg://','postgresql://'))
 evidence=', '.join("'%s',c.evidence->'%s'"%(k,k) for k in EVIDENCE)
 counts=collections.Counter(); targetcounts=collections.Counter(); before={}
 try:
  async with connection.transaction(readonly=True,isolation='repeatable_read'):
   for table in ['crm_contact_imports','crm_property_contact_claims','crm_owner_notes','crm_lead_notes','crm_owner_workspaces','crm_lead_workspaces','crm_saved_leads']:
    records=await connection.fetch(f"SELECT id,md5(to_jsonb(t)::text) digest FROM {table} t WHERE organization_id=$1 ORDER BY id",'f195cfaf-6e25-4ff0-8bbf-ca84509ae927')
    before[table]={str(r['id']):r['digest'] for r in records}
   metadata=await connection.fetch("SELECT id,mapping->'sheets' sheets FROM crm_contact_imports WHERE id=ANY($1::int[])",list(ids))
   size_units={(m['id'],str(sheet.get('sheet_name') or '')):source_size_unit(sheet.get('field_map') or {}) for m in metadata for sheet in (json.loads(m['sheets']) if isinstance(m['sheets'],str) else m['sheets'] or [])}
   sql=f'''SELECT c.id,c.import_id,c.source_sheet,c.source_row_number,c.area_name,c.project_name,c.building_name,c.unit_number,c.property_type,c.party_role,c.procedure_type,c.transaction_date,c.transaction_price_aed,c.ownership_status,jsonb_strip_nulls(jsonb_build_object({evidence})) evidence FROM crm_property_contact_claims c WHERE c.organization_id=$1 AND c.import_id=ANY($2::int[]) ORDER BY c.import_id,c.source_sheet,c.source_row_number'''
   with (ROOT/'rows.jsonl').open('w') as out,(ROOT/'baseline-matched.jsonl').open('w') as matched,(ROOT/'all-rows.jsonl').open('w') as allout:
    async for record in connection.cursor(sql,'f195cfaf-6e25-4ff0-8bbf-ca84509ae927',list(ids),prefetch=1000):
     r=dict(record);r['evidence']=json.loads(r['evidence']);e=r['evidence'];p=(ids[r['import_id']],r['source_sheet'],r['source_row_number']);original=ledger[p]
     for k in ('source_fields','raw_source_fields','original_property_fields'):e[k]=safe_source_fields(e.get(k))
     declared=size_units.get((r['import_id'],r['source_sheet']))
     if declared:e['source_size_unit']=declared
     elif not e.get('source_size_unit') and any(e['source_fields'].get(k) not in (None,'') for k in ('size_sqft','size_sqm','size_unknown')):e['source_size_unit']='unknown'
     source=_amount_match_source(_candidate(r));decision=e.get('amount_first_match') or {}
     value={'row_key':hashlib.sha256(json.dumps(p).encode()).hexdigest(),'filename':p[0],'sheet':p[1],'row':p[2],'source_event_id':original.get('source_event_id'),'source_unit_id':original.get('source_unit_id'),'original_category':original['category'],'primary_cause':fixed[p]['primary_cause'] if p in fixed else None,'source':source,'raw_fields':e.get('raw_source_fields') or e.get('source_fields') or {},'learned_size_units':e.get('inferred_size_unit'),'source_size_unit_inference':e.get('inferred_size_unit'),'source_declared_size_unit':e.get('source_size_unit'),'current_match':decision,'current_status':r['ownership_status'],'party_role':r['party_role'],'baseline_resolver':e.get('resolver_version'),'source_claim_id':r['id']}
     dump_line(allout,value);counts['all_named_rows']+=1
     if p in fixed:
      dump_line(out,value);targetcounts[value['primary_cause']]+=1
      if decision.get('status')=='matched':counts['already_matched_focus_rows']+=1
     if decision.get('status')=='matched' and str(decision.get('selected_event_key','')).startswith('sale:'):
      dump_line(matched,value);counts['baseline_matched_rows']+=1
 finally:await connection.close()
 assert dict(targetcounts)==CAUSES and counts['all_named_rows']==110327
 (ROOT/'database-before.json').write_text(json.dumps(before,sort_keys=True))
 counts.update({'focus_rows':sum(targetcounts.values()),'focus_source_events':len({r['source_event_id'] for r in fixed.values()})})
 (ROOT/'baseline-summary.json').write_text(json.dumps({'counts':dict(counts),'categories':dict(targetcounts),'code_files':len(code)},indent=2))
 print(json.dumps({'counts':dict(counts),'categories':dict(targetcounts),'code_files':len(code)}))
asyncio.run(main())
