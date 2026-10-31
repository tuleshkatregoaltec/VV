import importlib.util, unittest
from pathlib import Path
P=Path(__file__).parent
spec=importlib.util.spec_from_file_location('safety',P/'engine-safety.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
s.engine.factor=s.guarded_factor
class Sizes:
 def infer(self,r):return None
def source(project=None):
 return {'source_event_id':'source','source_unit_id':'unit','source':{'event_family':'sale','amount_aed':100,'area_name':'Dubai Marina','project_name':project,'building_name':'Tower 1','unit_number':'101','original_identifiers':{'unit_number':'101'},'transaction_date':'2020-01-01','property_type':'Flat'}}
def target(project='Named Project A'):
 return {'event_family':'sale','event_key':'a','amount_aed':100,'area_name':'Dubai Marina','project_name':project,'building_name':'Tower 1','unit_number':'101','property_type':'Flat','size_sqft':1000,'transaction_date':'2020-01-01'}
def choose(r,t=None):return s.engine.select(r,[t or target()],0,s.AliasModel(),Sizes())
class Tests(unittest.TestCase):
 def test_broad_area_and_generic_tower_not_named_scope(self):self.assertNotEqual(choose(source())['status'],'new_supported_inferred')
 def test_independent_matching_named_project_permits_scope(self):self.assertEqual(choose(source('Named Project A'))['status'],'new_supported_inferred')
 def test_different_project_cannot_supply_scope(self):self.assertNotEqual(choose(source('Named Project B'))['status'],'new_supported_inferred')
 def test_project_equal_to_broad_area_insufficient(self):self.assertNotEqual(choose(source('Dubai Marina'),target('Dubai Marina'))['status'],'new_supported_inferred')
 def test_normalized_recovery_not_original_project_evidence(self):
  r=source('Named Project A');r['raw_fields']={'project_name':''};self.assertNotEqual(choose(r)['status'],'new_supported_inferred')
 def test_parent_proof_requires_query_exclusion_and_independent_units(self):
  a={'kind':'parent','accepted':True,'scope':'dubaimarina','baseline_only':True,'query_unit_excluded':True,'independent_registry_units':2,'independent_source_units':2,'distinct_destinations':1};self.assertEqual(s.proof(source()['source'],target(),{'learned_aliases':[a]}),'independently_scoped_parent_alias');a['query_unit_excluded']=False;self.assertIsNone(s.proof(source()['source'],target(),{'learned_aliases':[a]}))
 def test_masked_holdout_uses_same_generic_guard(self):
  r=source();x=s.engine.select(r,[target()],0,s.AliasModel(),Sizes(),mask=True);self.assertNotEqual(x['status'],'new_supported_inferred')
if __name__=='__main__':unittest.main()
