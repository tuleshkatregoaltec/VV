import importlib.util, unittest
from pathlib import Path
P=Path(__file__).parent;spec=importlib.util.spec_from_file_location('namespace',P/'engine-namespace-all.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def source(project='Arabian Ranches lll - Joy',label='909',unit='null'):
 return {'area_name':'','project_name':project,'building_name':label,'property_type':'Building','unit_number':'','original_identifiers':{'building_number':'R3 Joy-V-909','plot_number':'AR3.A.10','unit_number':unit},'raw_location_fields':{'area_name':'','building_name':label,'project_name':project}}
def target():return {'area_name':'Arabian Ranches 3','project_name':'Arabian Ranches 3','building_name':'Joy','unit_number':'909','property_type':'Villa'}
class Tests(unittest.TestCase):
 def test_named_master_child_context_is_preserved_and_normalized(self):
  old=source();new,proof=m.normalize_context(old);self.assertEqual(old['project_name'],'Arabian Ranches lll - Joy');self.assertTrue(proof);self.assertIsNotNone(m.source_namespace(new,target()));self.assertIsNotNone(m.qualified(new,target()))
 def test_numeric_building_disagreement_cannot_be_overridden(self):
  new,_=m.normalize_context(source(label='910'));self.assertIsNone(m.source_namespace(new,target()))
 def test_other_original_unit_conflict_cannot_be_overridden(self):
  new,_=m.normalize_context(source(unit='910'));self.assertIsNone(m.source_namespace(new,target()))
 def test_wrong_named_subcommunity_cannot_be_overridden(self):
  old=source(project='Arabian Ranches III - Sun');new,proof=m.normalize_context(old);self.assertFalse(proof);self.assertIsNone(m.source_namespace(new,target()))
 def test_missing_full_original_code_cannot_be_inferred_from_suffix(self):
  old=source();old['original_identifiers']['building_number']='909';new,proof=m.normalize_context(old);self.assertFalse(proof);self.assertIsNone(m.source_namespace(new,target()))
if __name__=='__main__':unittest.main()
