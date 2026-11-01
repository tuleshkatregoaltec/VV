import importlib.util
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).parent

def mod(name,file):
 spec=importlib.util.spec_from_file_location(name,P/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
c4=mod('community_c4','community-c4.py');b=mod('community_base4','community-tests.py')

def select(r,targets):
 with patch.object(c4,'history',return_value=targets):return c4.select(r,None,b.c.Communities(b.PLACE),b.c.AliasModel(places=b.PLACE),b.Sizes())

class Tests(unittest.TestCase):
 def test_disagreeing_date_allowed_only_whole_history_unique(self):
  x=select(b.row(),[b.target(date='2023-01-01')]);self.assertEqual(x['status'],c4.STATUS);self.assertFalse(x['date_evidence']['exact']);self.assertFalse(x['date_evidence']['used_to_remove_competitors']);self.assertEqual(x['date_color'],'yellow')
 def test_missing_source_date_allowed(self):self.assertEqual(select(b.row(transaction_date=None),[b.target()])['status'],c4.STATUS)
 def test_years_apart_same_property_other_event_veto(self):self.assertEqual(select(b.row(),[b.target(),b.target(date='2023-01-01',key='b')])['status'],'unresolved')
 def test_years_apart_other_property_event_veto(self):self.assertEqual(select(b.row(),[b.target(),b.target('102','2023-01-01',key='b')])['status'],'unresolved')
 def test_unknown_size_event_any_year_veto(self):self.assertEqual(select(b.row(),[b.target(),b.target('102','2023-01-01',size=None,key='b')])['status'],'unresolved')
 def test_unknown_type_event_any_year_veto(self):self.assertEqual(select(b.row(),[b.target(),b.target('102','2023-01-01',key='b',property_type='Unknown')])['status'],'unresolved')
 def test_broad_source_cannot_filter_other_physical_form(self):self.assertEqual(select(b.row(property_type='Residential'),[b.target(),b.target('102','2023-01-01',key='b',property_type='Plot')])['status'],'unresolved')
 def test_explicit_source_form_still_rejects_incompatible_form(self):self.assertEqual(select(b.row(),[b.target(),b.target('102','2023-01-01',key='b',property_type='Plot')])['status'],c4.STATUS)
 def test_original_child_and_location_conflicts_never_overridden(self):
  self.assertEqual(select(b.row(original_identifiers={'building_number':'V999'}),[b.target('V101')])['status'],'unresolved');self.assertEqual(select(b.row(project_name='Wrong Phase'),[b.target()])['status'],'unresolved')
 def test_both_size_interpretations_considered_across_history(self):
  r=b.row(size_unknown='100',size_sqft='99999');r['source_declared_size_unit']='unknown';self.assertEqual(select(r,[b.target(size='100'),b.target('102','2023-01-01',size='1076.391041671',key='b')])['status'],'unresolved')
 def test_history_sql_uncapped_and_decimal_authoritative(self):
  with tempfile.TemporaryDirectory() as td:
   idx=b.c.Index(Path(td)/'index.sqlite');idx.db.execute('CREATE TABLE sale(event_rowid INTEGER,amount REAL,community TEXT,day TEXT,size REAL,payload TEXT)')
   for n in range(20):
    t=b.target(str(n),date=f'{2000+n}-01-01',key=str(n),amount_aed='102.0001');idx.db.execute('INSERT INTO sale VALUES(?,?,?,?,?,?)',(n,float(t['amount_aed']),'testcommunity',t['transaction_date'],1000,json.dumps(t)))
   t=b.target('out',amount_aed='102.0001001');idx.db.execute('INSERT INTO sale VALUES(?,?,?,?,?,?)',(99,float(t['amount_aed']),'testcommunity',None,1000,json.dumps(t)));self.assertEqual(len(c4.history(idx,'testcommunity',Decimal('100.0001'))),20)

if __name__=='__main__':unittest.main()
