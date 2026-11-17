import importlib.util
import unittest
from pathlib import Path
P=Path(__file__).parent

def mod(name,file):
 spec=importlib.util.spec_from_file_location(name,P/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
c3=mod('community_c3','community-c3.py');b=mod('community_base','community-tests.py')

def select(r,ts):return c3.select(r,b.Pool(ts),b.c.Communities(b.PLACE),b.c.AliasModel(places=b.PLACE),b.Sizes())

class Tests(unittest.TestCase):
 def test_broad_raw_type_preserved_without_physical_corroboration(self):
  x=select(b.row(property_type='Residential'),[b.target()]);self.assertEqual(x['status'],c3.STATUS);self.assertEqual(x['candidate_evidence']['raw_source_property_type'],'Residential');self.assertFalse(x['candidate_evidence']['physical_type_corroboration'])
 def test_building_and_unit_do_not_narrow_physical_form(self):
  for source_type in ('Building','Unit'):
   for target_type in ('Villa','Flat','Plot'):
    self.assertEqual(select(b.row(property_type=source_type),[b.target(property_type=target_type)])['status'],c3.STATUS)
 def test_residential_plot_rival_retained(self):
  x=select(b.row(property_type='Residential'),[b.target(),b.target('102','2020-01-02',key='b',property_type='Plot')]);self.assertEqual(x['status'],'unresolved');self.assertEqual(x['near_competitor_count'],1)
 def test_unknown_rival_type_retained(self):
  self.assertEqual(select(b.row(property_type='Unit'),[b.target(),b.target('102',None,key='b',property_type='Unknown')])['status'],'unresolved')
 def test_specific_plot_villa_conflict_preserved(self):self.assertEqual(select(b.row(property_type='Land'),[b.target()])['status'],'unresolved')
 def test_blank_and_unlisted_type_not_mapped(self):
  for t in ('','Commercial','Unknown'):self.assertEqual(select(b.row(property_type=t),[b.target()])['status'],'unresolved')
 def test_possible_child_id_conflict_not_erased_by_broad_type(self):
  r=b.row(property_type='Residential',original_identifiers={'plot_pre_reg_number':'P999'});self.assertEqual(select(r,[b.target('P101')])['status'],'unresolved')

if __name__=='__main__':unittest.main()
