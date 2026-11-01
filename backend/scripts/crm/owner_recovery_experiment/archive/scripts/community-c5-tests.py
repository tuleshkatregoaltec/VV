import copy
import importlib.util
import unittest
from pathlib import Path
P=Path(__file__).parent
spec=importlib.util.spec_from_file_location('community_c5',P/'community-c5.py');c5=importlib.util.module_from_spec(spec);spec.loader.exec_module(c5)

PLACES=[{'area_key':'testcommunity2','area_label':'Test Community 2','building_key':'testcommunity2','building_label':'','project_label':'','match_rank':2,'location_id':1,'path_key':'testcommunity2'},{'area_key':'othercommunity','area_label':'Other Community','building_key':'othercommunity','building_label':'','project_label':'','match_rank':2,'location_id':2,'path_key':'othercommunity'}]

def row(n=0):
 value=f'Test Community {n+3}'
 return {'row_key':f'r{n}','filename':'file.xlsx','sheet':'S','row':100+n,'source_event_id':f'e{n}','source_unit_id':f'q{n}','raw_fields':{'master_project':value},'source':{'area_name':value,'project_name':'Phase A','building_name':'','raw_location_fields':{'area_name':value},'original_identifiers':{'unit_number':''},'source_filename':'file.xlsx','source_sheet':'S'}}

def training(n=12,mixed=False):
 result=[]
 for i in range(n):
  s={'source_unit_id':f't{i}','source':{'source_filename':'file.xlsx','source_sheet':'S'}}
  t={'area_name':'Other Community' if mixed and i==0 else 'Test Community 2','building_name':'Building A','project_name':'Phase A','unit_number':str(i+1),'property_type':'Villa'}
  result.append((s,t))
 return result

def model(rows=None,train=None):return c5.Repair(rows or [row(i) for i in range(12)],train or training(),c5.c1.Communities(PLACES))

class Tests(unittest.TestCase):
 def test_target_independent_slope_sequence_and_unanimous_training(self):
  r=row();before=copy.deepcopy(r);copied,e=model().apply(r);self.assertEqual(copied['source']['area_name'],'Test Community 2');self.assertEqual(r,before);self.assertEqual(copied['raw_fields']['master_project'],'Test Community 3');self.assertTrue(e['training_support']['accepted']);self.assertEqual(copied['source']['project_name'],'Phase A')
 def test_not_enough_contiguous_rows_no_repair(self):self.assertIsNone(model(rows=[row(i) for i in range(9)]).apply(row())[1])
 def test_suffix_slope_not_one_no_repair(self):
  rows=[row(i) for i in range(12)]
  for i,r in enumerate(rows):r['raw_fields']['master_project']=f'Test Community {2*i+3}'
  self.assertFalse(c5.Repair(rows,training(),c5.c1.Communities(PLACES)).blocks)
 def test_source_row_gap_breaks_contiguity(self):
  rows=[row(i) for i in range(12)]
  for r in rows[6:]:r['row']+=1
  self.assertFalse(c5.Repair(rows,training(),c5.c1.Communities(PLACES)).blocks)
 def test_mixed_training_communities_reject(self):self.assertIsNone(model(train=training(mixed=True)).apply(row())[1])
 def test_minimum_independent_physical_properties(self):self.assertIsNone(model(train=training(9)).apply(row())[1])
 def test_duplicate_events_not_independent_property_votes(self):self.assertIsNone(model(train=training(1)*20).apply(row())[1])
 def test_query_source_and_target_property_both_excluded(self):
  m=model(train=training(12));r=row();r['source_unit_id']='t0';support=m.support(r,training()[1][1]);self.assertEqual(support['independent_properties'],10);self.assertTrue(support['candidate_target_property_excluded'])
 def test_candidate_exclusion_can_invalidate_minimum(self):self.assertFalse(model(train=training(10)).support(row(),training()[0][1])['accepted'])
 def test_never_override_valid_other_community(self):
  r=row();r['source']['area_name']='Other Community';self.assertIsNone(model().apply(r)[1])
 def test_never_override_precise_other_community_label(self):
  r=row();r['source']['project_name']='Other Community';self.assertIsNone(model().apply(r)[1])
 def test_prefix_must_match_canonical_community(self):
  train=training()
  for s,t in train:t['area_name']='Other Community'
  self.assertIsNone(model(train=train).apply(row())[1])
 def test_unknown_community_training_votes_are_not_dropped(self):
  train=training();train[0][1]['area_name']='Unresolved Legal District';m=model(train=train);self.assertFalse(m.support(row())['accepted']);self.assertEqual(m.support(row())['unknown_community_properties'],1)
 def test_original_raw_project_other_community_blocks_repair(self):
  r=row();r['raw_fields']['project_name']='Other Community';self.assertIsNone(model().apply(r)[1])
 def test_original_qualified_other_community_blocks_repair(self):
  r=row();r['raw_fields']['project_name']='Other Community - Phase A';self.assertIsNone(model().apply(r)[1])
 def test_original_raw_location_other_community_blocks_repair(self):
  r=row();r['source']['raw_location_fields']['area_name']='Other Community';self.assertIsNone(model().apply(r)[1])
 def test_unrelated_source_row_untouched(self):
  r=row();r['row_key']='outside';copied,e=model().apply(r);self.assertIs(copied,r);self.assertIsNone(e)

if __name__=='__main__':unittest.main()
