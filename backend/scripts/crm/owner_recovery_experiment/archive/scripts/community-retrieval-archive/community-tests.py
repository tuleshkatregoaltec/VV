import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
import community_fingerprint as c

PLACE=[{'area_key':'testcommunity','area_label':'Test Community','building_key':'testcommunity','building_label':'','project_label':'','match_rank':2,'location_id':1,'path_key':'testcommunity'}]

class Sizes:
    def infer(self,source):return None

class Pool:
    def __init__(self,targets):self.targets=targets
    def query(self,community,amount,day,near=False):
        for t in self.targets:
            td=c.frozen.day(t.get('transaction_date'))
            if not c.tm.amounts_match(amount,t['amount_aed']):continue
            if near:
                if td is None or abs((td-day).days)<=14:yield t
            elif td==day:yield t

def row(**kwargs):
    s={'event_family':'sale','area_name':'Test Community','project_name':'','building_name':'','property_type':'Villa','amount_aed':'100','transaction_date':'2020-01-01','size_sqft':'1000','original_identifiers':{},'raw_location_fields':{'area_name':'Test Community','project_name':'','building_name':''}}
    s.update(kwargs)
    return {'row_key':'r','source_event_id':'s','source_unit_id':'u','source':s,'raw_fields':{'master_project':'Test Community'},'source_declared_size_unit':'sqft','primary_cause':'no_original_role_correct_full_identifier'}

def target(unit='101',date='2020-01-01',size='1000',key='a',**kwargs):
    t={'event_family':'sale','event_key':key,'area_name':'Test Community','project_name':'Project','building_name':'Named Place','unit_number':unit,'property_type':'Villa','amount_aed':'100','size_sqft':size,'transaction_date':date}
    t.update(kwargs);return t

def select(r,ts):return c.select(r,Pool(ts),c.Communities(PLACE),c.AliasModel(places=PLACE),Sizes())

class Tests(unittest.TestCase):
    def test_complete_joint_fingerprint_conditional_only(self):
        r=row();before=json.dumps(r,sort_keys=True);d=select(r,[target()]);self.assertEqual(d['status'],'conditional_rule_c_candidate');self.assertEqual(json.dumps(r,sort_keys=True),before)
    def test_years_apart_property_can_be_separated(self):
        self.assertEqual(select(row(),[target(),target('102','2023-01-01',key='b')])['status'],'conditional_rule_c_candidate')
    def test_nearby_different_property_bulk_registration_veto(self):
        d=select(row(),[target(),target('102','2020-01-15',key='b')]);self.assertEqual(d['reason'],'nearby_or_undated_same_community_price_size_competitor')
    def test_fifteen_day_other_property_does_not_veto(self):
        self.assertEqual(select(row(),[target(),target('102','2020-01-16',key='b')])['status'],'conditional_rule_c_candidate')
    def test_unknown_date_other_property_veto(self):
        self.assertEqual(select(row(),[target(),target('102',None,key='b')])['near_competitor_count'],1)
    def test_unknown_size_nearby_property_veto(self):
        self.assertEqual(select(row(),[target(),target('102','2020-01-02',None,'b')])['near_competitor_count'],1)
    def test_different_size_nearby_property_can_be_removed(self):
        self.assertEqual(select(row(),[target(),target('102','2020-01-02','2000','b')])['status'],'conditional_rule_c_candidate')
    def test_known_different_physical_type_rival_not_competitor(self):
        self.assertEqual(select(row(),[target(),target('102','2020-01-02',key='b',property_type='Plot')])['status'],'conditional_rule_c_candidate')
    def test_same_day_multiple_events_even_same_property_veto(self):
        self.assertEqual(select(row(),[target(),target(key='b')])['reason'],'multiple_exactday_fingerprint_events_or_properties')
    def test_missing_source_day_abstains(self):self.assertEqual(select(row(transaction_date=None),[target()])['status'],'unresolved')
    def test_unknown_source_size_unit_abstains(self):
        r=row(size_unknown='1000');r['source_declared_size_unit']='unknown';self.assertEqual(select(r,[target()])['status'],'unresolved')
    def test_missing_target_size_abstains(self):self.assertEqual(select(row(),[target(size=None)])['status'],'unresolved')
    def test_unknown_source_physical_type_abstains(self):self.assertEqual(select(row(property_type='Building'),[target()])['reason'],'unknown_source_physical_type')
    def test_explicit_plot_villa_mismatch_abstains(self):self.assertEqual(select(row(property_type='Land'),[target()])['status'],'unresolved')
    def test_original_unit_conflict_cannot_be_overridden(self):self.assertEqual(select(row(original_identifiers={'unit_number':'999'}),[target()])['status'],'unresolved')
    def test_placeholder_unit_ids_are_missing_not_contradictory(self):
        for missing in ('null','none','unknown','n/a','0','-'):
            self.assertEqual(select(row(original_identifiers={'unit_number':missing}),[target()])['status'],'conditional_rule_c_candidate')
    def test_plot_prereg_conflict_cannot_be_overridden(self):
        r=row(property_type='Plot',original_identifiers={'plot_pre_reg_number':'P999'});self.assertEqual(select(r,[target('P101',property_type='Plot')])['status'],'unresolved')
    def test_original_contradiction_category_abstains(self):
        r=row();r['primary_cause']='original_address_codes_contradict';self.assertEqual(select(r,[target()])['reason'],'original_address_contradiction_retained')
    def test_precise_project_conflict_veto(self):self.assertEqual(select(row(project_name='Other Project'),[target()])['status'],'unresolved')
    def test_filename_only_community_is_not_proof(self):
        r=row(raw_location_fields={},source_filename='Test Community.xlsx');r['raw_fields']={};self.assertEqual(select(r,[target()])['status'],'unresolved')
    def test_wide_district_is_not_community(self):
        p=[{**PLACE[0],'area_key':'district','area_label':'District','building_key':'namedplace','match_rank':1}]
        r=row(area_name='District',raw_location_fields={'area_name':'District'});r['raw_fields']={'master_project':'District'};self.assertIsNone(c.Communities(p).source(r)[0])
    def test_qualified_original_community_prefix(self):
        r=row(raw_location_fields={'project_name':'Test Community - Phase 2'});r['raw_fields']={};self.assertEqual(c.Communities(PLACE).source(r)[0],'testcommunity')
    def test_embedded_full_r3_code_leak_excluded(self):
        for text in ('R3 Sun-V204','R3 Sun-V-204','Sun-V204'):
            r=row(original_identifiers={'building_number':'R3 Sun-V-204'},raw_location_fields={'building_name':text});self.assertIn('raw_location_fields.building_name',c.location_id_leaks(r))
    def test_numeric_child_in_normalized_location_excluded(self):
        r=row(building_name='Villa 204',original_identifiers={'unit_number':'204'});self.assertIn('source.building_name',c.location_id_leaks(r))
    def test_mask_removes_all_identifier_copies(self):
        r=row(unit_number='101',original_identifiers={'unit_number':'101'});r['raw_fields']['unit_number']='101';m=c.masked_row(r);self.assertFalse(m['source']['unit_number']);self.assertNotIn('unit_number',m['raw_fields']);self.assertEqual(m['source']['original_identifiers'],{})
    def test_frozen_reverse_event_veto_retains_duplicate_buyers_sellers(self):
        a=row(original_identifiers={'unit_number':'101'});b=row(original_identifiers={'unit_number':'101'});b['source_unit_id']='u2';x={'status':'new_supported_inferred','selected':c.target_summary(target())};z=json.loads(json.dumps(x));c.frozen.veto([(a,x),(b,z)],[],[]);self.assertEqual(x['status'],'new_supported_inferred')
    def test_frozen_reverse_event_veto_rejects_conflicting_ids(self):
        a=row(original_identifiers={'unit_number':'101'});b=row(original_identifiers={'unit_number':'999'});b['source_unit_id']='u2';x={'status':'new_supported_inferred','selected':c.target_summary(target())};z=json.loads(json.dumps(x));c.frozen.veto([(a,x),(b,z)],[],[]);self.assertEqual(x['status'],'tentative')
    def test_decimal_index_boundary_and_uncapped_competitors(self):
        with tempfile.TemporaryDirectory() as td:
            idx=c.Index(Path(td)/'index.sqlite');idx.db.execute('CREATE TABLE sale(event_rowid INTEGER,amount REAL,community TEXT,day TEXT,size REAL,payload TEXT)')
            ts=[target(str(n),key=str(n),amount_aed='102.0001') for n in range(20)]
            ts.append(target('out',key='out',amount_aed='102.0001001'))
            for n,t in enumerate(ts):idx.db.execute('INSERT INTO sale VALUES(?,?,?,?,?,?)',(n,float(t['amount_aed']),'testcommunity','2020-01-01',1000,json.dumps(t)))
            self.assertEqual(len(list(idx.query('testcommunity',Decimal('100.0001'),date(2020,1,1)))),20)

if __name__=='__main__':unittest.main(verbosity=1)
