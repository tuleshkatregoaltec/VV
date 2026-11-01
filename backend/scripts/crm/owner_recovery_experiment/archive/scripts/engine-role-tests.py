import importlib.util, unittest
from pathlib import Path
P=Path(__file__).parent;spec=importlib.util.spec_from_file_location('role',P/'engine-role-reconciliation.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def row(other=3):
 a={'kind':'parent','source_field':'plot_number','source_key':'parent1','accepted':True,'scope':'namedproject','baseline_only':True,'query_unit_excluded':True,'distinct_destinations':1,'independent_registry_units':other,'independent_source_units':other}
 return {'row_key':'r','source_event_id':'e','source_unit_id':'u','filename':'f','sheet':'s','row':1,'primary_cause':'original_address_codes_contradict','reason':'original_address_contradiction_retained','source':{'building_name':'Named Place','property_type':'Villa','original_identifiers':{'building_number':'ABC101','plot_number':'PARENT1','unit_number':'null'}},'selected':{'target':{'unit_number':'ABC101'},'learned_aliases':[a],'conflicts':[],'location_ok':True,'physical_type_compatible':True}}
class Tests(unittest.TestCase):
 def test_conditional_proposal_requires_all_role_evidence(self):self.assertTrue(m.evaluate(row())['conditional_supported_proposal'])
 def test_three_other_units_minimum(self):self.assertFalse(m.evaluate(row(2))['conditional_supported_proposal'])
 def test_mixed_parent_cannot_explain_original_plot(self):
  r=row();r['selected']['learned_aliases'][0]['distinct_destinations']=2;self.assertFalse(m.evaluate(r)['conditional_supported_proposal'])
 def test_numeric_label_not_explained_by_suffix_alone(self):
  r=row();r['source']['building_name']='101';self.assertFalse(m.evaluate(r)['conditional_supported_proposal'])
 def test_other_event_ambiguity_is_not_overridden_by_role_proof(self):
  r=row();r['reason']='ambiguous_transaction_or_close_date_competitor';x=m.evaluate(r);self.assertTrue(x['all_original_identifier_roles_explained']);self.assertFalse(x['conditional_supported_proposal'])
 def test_residual_location_conflict_is_rejection(self):
  r=row();r['selected']['conflicts']=['area_or_community_conflict'];self.assertFalse(m.evaluate(r)['conditional_supported_proposal'])
if __name__=='__main__':unittest.main()
