import importlib.util
import unittest
from pathlib import Path
P=Path(__file__).parent

def module(name,file):
 spec=importlib.util.spec_from_file_location(name,P/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
c2=module('community_c2','community-c2.py');base=module('community_tests','community-tests.py')

def select(r,ts):return c2.select(r,base.Pool(ts),base.c.Communities(base.PLACE),base.c.AliasModel(places=base.PLACE),base.Sizes())

def unknown(raw='100'):
 r=base.row(size_unknown=raw,size_sqft='999999');r['source_declared_size_unit']='unknown';return r

class Tests(unittest.TestCase):
 def test_candidate_dependent_sqm_interpretation(self):
  x=select(unknown(),[base.target(size='1076.391041671')]);self.assertEqual(x['status'],c2.STATUS);self.assertEqual(x['selected_size_hypotheses'],['sqm']);self.assertTrue(x['size_evidence']['candidate_dependent'])
 def test_unique_across_both_interpretations_required(self):
  x=select(unknown(),[base.target(size='100'),base.target('102',size='1076.391041671',key='b')]);self.assertEqual(x['status'],'unresolved');self.assertEqual(x['exactday_candidate_count'],2)
 def test_nearby_other_interpretation_veto(self):
  x=select(unknown(),[base.target(size='1076.391041671'),base.target('102','2020-01-02',size='100',key='b')]);self.assertEqual(x['near_competitor_count'],1);self.assertEqual(x['status'],'unresolved')
 def test_unknown_size_competitor_veto(self):
  self.assertEqual(select(unknown(),[base.target(size='1076.391041671'),base.target('102',None,size=None,key='b')])['status'],'unresolved')
 def test_known_unit_not_reinterpreted(self):
  self.assertEqual(select(base.row(size_unknown='100',size_sqft='100'),[base.target(size='1076.391041671')])['status'],'unresolved')
 def test_sole_event_may_fit_both_without_claiming_unique_unit(self):
  x=select(unknown('1'),[base.target(size='10')]);self.assertEqual(x['status'],c2.STATUS);self.assertEqual(x['selected_size_hypotheses'],['sqft','sqm'])
 def test_child_id_conflict_remains(self):
  r=unknown();r['source']['original_identifiers']={'building_number':'V999'};self.assertEqual(select(r,[base.target('V101',size='1076.391041671')])['status'],'unresolved')
 def test_wide_or_filename_only_scope_still_abstains(self):
  r=unknown();r['raw_fields']={};r['source']['raw_location_fields']={};self.assertEqual(select(r,[base.target(size='100')])['status'],'unresolved')

if __name__=='__main__':unittest.main()
