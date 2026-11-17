import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
import community_fingerprint as c
P=Path(__file__).parent

def mod(name,file):
 spec=importlib.util.spec_from_file_location(name,P/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
c3=mod('retrieval_c3','community-c3.py');c4=mod('retrieval_c4','community-c4.py');base=mod('retrieval_base','community-tests.py')
PLACES=json.loads(c.PLACES.read_text())

class Tests(unittest.TestCase):
 def test_actual_parent_community_label_in_legal_district_is_definite(self):
  m=c.Communities(PLACES).memberships({'area_name':'Jabal Ali 1','building_name':'Al Furjan','project_name':''});self.assertEqual(m['definite'],['alfurjan']);self.assertIn('alfurjan',m['possible'])
 def test_legal_district_only_is_possible_rival_not_positive(self):
  m=c.Communities(PLACES).memberships({'area_name':'Jabal Ali 1','building_name':'','project_name':''});self.assertIn('alfurjan',m['possible']);self.assertEqual(m['definite'],[])
 def test_conflicting_explicit_communities_never_definite(self):
  m=c.Communities(PLACES).memberships({'area_name':'Dubai Marina','building_name':'Al Furjan'});self.assertEqual(m['definite'],[]);self.assertIn('alfurjan',m['possible']);self.assertIn('dubaimarina',m['possible'])
 def test_explicit_project_community_in_legal_area_is_definite(self):
  m=c.Communities(PLACES).memberships({'area_name':'Jabal Ali 1','project_name':'Al Furjan','building_name':''});self.assertEqual(m['definite'],['alfurjan'])
 def test_unknown_generic_building_cannot_supply_definite_community(self):
  m=c.Communities(PLACES).memberships({'area_name':'Jabal Ali 1','building_name':'Tower 1'});self.assertEqual(m['definite'],[]);self.assertIn('alfurjan',m['possible'])
 def test_missing_or_city_only_geography_retained_as_global_possible_rival(self):
  for area in ('','Dubai','unknown'):
   m=c.Communities(PLACES).memberships({'area_name':area,'building_name':'Unknown Building'});self.assertEqual(m['definite'],[]);self.assertIn('__unscoped__',m['possible'])
 def test_narrow_source_does_not_promote_ambiguous_target(self):
  s=c.source_frame(base.row());t=base.target();t['_community_positive_evidence']=False;ok,detail=c.candidate_detail(s,t,c.AliasModel(places=base.PLACE),Decimal(1000));self.assertFalse(ok);self.assertIn('ambiguous_community_membership_rival_only',detail['conflicts'])
 def test_broad_source_does_not_promote_ambiguous_target(self):
  s=c.source_frame(base.row(property_type='Residential'));t=base.target();t['_community_positive_evidence']=False;self.assertFalse(c3.candidate_detail(s,t,c.AliasModel(places=base.PLACE),Decimal(1000))[0])
 def test_index_marks_possible_rivals_and_keeps_them_in_near_and_history(self):
  with tempfile.TemporaryDirectory() as td:
   idx=c.Index(Path(td)/'index.sqlite');idx.db.execute('CREATE TABLE sale(event_rowid INTEGER,amount REAL,community TEXT,day TEXT,size REAL,payload TEXT)')
   t=base.target();t['_community_membership']={'definite':[],'possible':['testcommunity']};idx.db.execute('INSERT INTO sale VALUES(?,?,?,?,?,?)',(1,100,'testcommunity','2020-01-01',1000,json.dumps(t)))
   exact=list(idx.query('testcommunity',Decimal(100),date(2020,1,1)));near=list(idx.query('testcommunity',Decimal(100),date(2020,1,1),near=True));history=c4.history(idx,'testcommunity',Decimal(100));self.assertEqual(len(exact),1);self.assertEqual(len(near),1);self.assertEqual(len(history),1);self.assertFalse(exact[0]['_community_positive_evidence']);self.assertFalse(history[0]['_community_positive_evidence'])

if __name__=='__main__':unittest.main()
