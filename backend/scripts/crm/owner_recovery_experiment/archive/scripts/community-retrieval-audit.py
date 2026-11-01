"""Confirm the seven previously omitted weak-reference events are now indexed."""
import json
import sqlite3
from pathlib import Path
import community_fingerprint as c
ROOT=Path(__file__).parent

def main():
    old=ROOT/'community-retrieval-archive/community-c4-holdout.jsonl'
    disagreements=[]
    for line in old.open():
        r=json.loads(line)
        if str(r.get('status','')).startswith('conditional_') and r.get('selected') and tuple(r['selected']['property'])!=tuple(r.get('weak_property',[])):disagreements.append(r)
    db=sqlite3.connect('file:'+str(ROOT/'community-index.sqlite')+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON')
    places=c.Communities(json.loads(c.PLACES.read_text()));checks=[]
    for r in disagreements:
        target=json.loads(db.execute('SELECT payload FROM baseline_target WHERE event_key=?',(r['weak_event'],)).fetchone()[0])
        expected=r['community_evidence']['community'];membership=places.memberships(target);amount=next(iter(c.tm._amounts(target)))[1]
        count=db.execute("SELECT count(*) FROM sale WHERE community=? AND amount BETWEEN ? AND ? AND json_extract(payload,'$.event_key')=?",(expected,float(amount)-2.000001,float(amount)+2.000001,target['event_key'])).fetchone()[0]
        checks.append({'source_event_id':r['source_event_id'],'weak_event':r['weak_event'],'expected_community':expected,'membership':membership,'indexed_records':count})
    assert len(checks)==7 and all(x['indexed_records'] and x['expected_community'] in x['membership']['possible'] for x in checks)
    metadata=dict(db.execute('SELECT key,value FROM metadata'));assert metadata['sale_events_scanned']=='993778'
    report={'check':'PASS','previously_omitted_weak_reference_events':len(checks),'now_indexed':sum(x['indexed_records']>0 for x in checks),'sale_events_scanned':int(metadata['sale_events_scanned']),'indexed_membership_records':int(metadata['indexed_records']),'checks':checks,'private_index_writes':db.total_changes,'old_disagreements_are_superseded_diagnostics':True}
    c.save('community-retrieval-audit.json',report);print(json.dumps({k:v for k,v in report.items() if k!='checks'},sort_keys=True))

if __name__=='__main__':main()
