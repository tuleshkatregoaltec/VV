"""Adversarial checks for offline recovery claims, not owner accuracy."""
import importlib.util, json, sqlite3, tempfile, unittest
from pathlib import Path
P=Path(__file__).parent
spec=importlib.util.spec_from_file_location('engine',P/'engine.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
class Model:
 def infer(self,s):return None
 def features(self,s,t):
  u=e.tm.identifier(str(s.get('original_identifiers',{}).get('unit_number') or ''));v=e.tm.identifier(t['unit_number'])
  return {'location':{'strength':'building','rules':['test_named_building'],'conflicts':[]},'identifier':{'strength':'unit' if u==v else 'none','scope':'child' if u==v else 'none','rules':[],'conflicts':['explicit_unit_identity_conflict'] if u and u!=v else []}}
def row(unit='',size=None,date='2020-01-01',cause='no_original_role_correct_full_identifier'):
 return {'source_event_id':'s','source_unit_id':'u','primary_cause':cause,'source':{'event_family':'sale','amount_aed':'100','building_name':'Named Place','unit_number':unit,'original_identifiers':{'unit_number':unit},'size_sqft':size,'transaction_date':date,'property_type':'Flat'}}
def target(unit='101',date='2020-01-01',size='1000',key='a'):
 return {'event_family':'sale','event_key':key,'sale_key':key,'amount_aed':100,'area_name':'Area','building_name':'Named Place','unit_number':unit,'property_type':'Flat','size_sqft':size,'transaction_date':date}
def select(r,ts):return e.select(r,ts,0,Model(),Model())
class Tests(unittest.TestCase):
 def test_missing_id_exact_date_corroboration(self):self.assertEqual(select(row(),[target()])['status'],'new_supported_inferred')
 def test_price_location_without_independent_evidence_tentative(self):self.assertEqual(select(row(date=None),[target()])['status'],'tentative')
 def test_date_cannot_remove_another_property(self):self.assertEqual(select(row(),[target(),target('102','2021-01-01',key='b')])['reason'],'multiple_properties_date_cannot_disambiguate')
 def test_nearby_same_property_registration_blocks_date(self):self.assertEqual(select(row('101'),[target(),target(date='2020-01-08',key='b')])['reason'],'ambiguous_transaction_or_close_date_competitor')
 def test_unknown_date_competitor_blocks_date(self):self.assertEqual(select(row('101'),[target(),target(date=None,key='b')])['reason'],'ambiguous_transaction_or_close_date_competitor')
 def test_distant_same_property_registration_date_selects(self):self.assertEqual(select(row('101'),[target(),target(date='2021-01-01',key='b')])['selected']['event_key'],'sale:a')
 def test_unknown_size_target_cannot_force_unique(self):self.assertEqual(select(row(size=1000),[target(),target('102',size=None,key='b')])['reason'],'unknown_target_size_prevents_uniqueness')
 def test_size_can_disambiguate_property(self):self.assertEqual(select(row(size=1000),[target(),target('102',size=1800,key='b')])['status'],'new_supported_inferred')
 def test_original_child_mismatch_cannot_be_overridden(self):self.assertEqual(select(row('999',size=1000),[target()])['status'],'tentative')
 def test_original_contradiction_retained(self):self.assertEqual(select(row('101',cause='original_address_codes_contradict'),[target()])['status'],'tentative')
 def test_property_plot_role_correct_child_mismatch_cannot_be_inferred(self):
  for kind,field in [('Flat','property_number'),('Plot','plot_number'),('Plot','property_number')]:
   r=row(size=1000);r['source']['property_type']=kind;r['source']['original_identifiers'][field]='ABC999';t=target('ABC101');t['property_type']=kind
   self.assertNotEqual(select(r,[t])['status'],'new_supported_inferred')
 def test_unknown_source_type_still_respects_original_villa_building_code(self):
  r=row(size=1000);r['source']['property_type']='Building';r['source']['original_identifiers']['building_number']='V999';t=target('V101');t['property_type']='Villa';self.assertNotEqual(select(r,[t])['status'],'new_supported_inferred')
 def test_conflicting_property_number_cannot_hide_behind_matching_unit(self):
  r=row('101',size=1000);r['source']['original_identifiers']['property_number']='999';self.assertNotEqual(select(r,[target()])['status'],'new_supported_inferred')
 def test_non_sale_source_cannot_get_sale_success(self):
  r=row('101');r['source']['event_family']='rental';self.assertNotEqual(select(r,[target()])['status'],'new_supported_inferred')
 def test_decimal_boundary_and_rentals_are_separate(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'s.sqlite';c=sqlite3.connect(p);c.execute('CREATE TABLE event(family TEXT,amount REAL,payload TEXT)')
   for family,amt,key in [('sale','102.0001','inside'),('sale','102.0001001','outside'),('rental','100.0001','rental')]:
    t=target(key=key);t.update(event_family=family,amount_aed=amt);c.execute('INSERT INTO event VALUES(?,?,?)',(family,float(amt),json.dumps(t)))
   c.commit();c.close();pool,rent=e.Pools(p).get('100.0001');self.assertEqual([x['event_key'] for x in pool],['inside']);self.assertEqual(rent,1)
 def test_generic_building_without_independent_context_cannot_qualify(self):
  r=row('101');r['source']['building_name']='Tower 1';x=select(r,[target()]);self.assertNotEqual(x['status'],'new_supported_inferred')
 def test_reverse_plot_identity_reuse_veto(self):
  rs=[]
  for n in (1,2):
   r=row();r['source']['property_type']='Plot';r['source']['original_identifiers']['plot_number']='ABC'+str(n);r['source_unit_id']='u'+str(n)
   x={'status':'new_supported_inferred','selected':{'event_key':'sale:x','property':['area','building','101']}};rs.append((r,x))
  e.veto(rs,[],[]);self.assertTrue(all(x['status']=='tentative' for r,x in rs))
 def test_reverse_event_reuse_veto(self):
  a=row('101');b=row('999');b.update(source_event_id='s2',source_unit_id='u2');x=select(a,[target()]);z={'status':'new_supported_inferred','selected':{'event_key':'sale:a','property':list(e.prop(target()))}}
  e.veto([(a,x),(b,z)],[],[]);self.assertEqual(x['status'],'tentative');self.assertEqual(z['status'],'tentative')
if __name__=='__main__':unittest.main(verbosity=1)
