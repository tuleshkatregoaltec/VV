"""Separate predeclared conditional community/price/date/size experiment."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import engine as frozen
import aliases as alias_module
from aliases import AliasModel, _area_key, _place_key, fields
from app.crm.owner_matching_policy import SheetSizeEvidence, qualified

tm = frozen.tm
SNAPSHOT = Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/snapshot.sqlite')
PLACES = Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json')
PROFILE = 'community_joint_fingerprint'
RULES = {
    'version': 'community-joint-fingerprint-C1.1-retrieval2',
    'conditional_only': True,
    'source': 'explicit sale, positive amount, exact known day, explicit independently catalog-normalized community; no filename-only or wide-district scope',
    'community_catalog': 'DXBI rank-2 self-named community nodes plus area labels distinct from every legal area key; source must explicitly contain exact master/community or a qualified community prefix in original location fields',
    'amount_tolerance_aed': '2',
    'size': 'known source unit or frozen TRAIN-only sheet-unit inference >=10 independent properties and >=95% exclusive votes, excluding query source unit; target known size within max(50sqft,2% source)',
    'physical_type': 'both source and target require a recognized physical kind; kinds must agree and frozen explicit-use incompatibilities still veto',
    'event': 'one distinct event and one complete property after community+amount+exactday+size+type+original child-role and precise-label conflict checks',
    'competitors': 'veto EVERY other sale event/property in complete same-community amount+-2 pool dated within14days or date unknown, if size compatible or unknown and physical type compatible; precise-label disagreement does not remove this conservative competitor veto',
    'ids': 'no raw role-correct child-ID contradiction; original contradictory-address cohort abstains; missing IDs proposed only, never written into raw fields',
    'holdout': 'inherit frozen connected target-property/source-unit split; size/alias training only frozen TRAIN pairs; mask original/normalized IDs; exclude encoded-ID leakage in remaining location fields before selection',
    'reuse': 'same frozen engine global veto: focus against ALL live baseline rows plus conditional proposals; holdout against TRAIN-only known refs plus all masked holdout proposals; buyer/seller duplicate refs with agreeing IDs are permitted',
    'weak_labels': 'same-event/property agreement against prior matches is diagnostic agreement, not truth or precision',
    'retrieval': 'Include explicit canonical area/building/project and validated catalog place/legal-area community bridges. Ambiguous legal-area-only membership is a possible rival, never positive community proof.',
    'uncapped': True,
}
ALL_IDS = tuple(dict.fromkeys((*frozen.IDENTIFIER_FIELDS,'land_number','land_sub_number','municipality_number','municipality_sub_number')))
SAFE_TARGET = ('event_family','event_key','area_name','project_name','building_name','unit_number','property_type','amount_aed','sale_amount_aed','size_sqft','transaction_date','building_key','area_key','location_name')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def save(name, value):
    (ROOT/name).write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+'\n')


def freeze():
    paths=[Path(__file__),ROOT/'engine.py',ROOT/'aliases.py',ROOT/'rows.jsonl',ROOT/'baseline-matched.jsonl',ROOT/'engine-training-pairs.jsonl',ROOT/'alias-dependency-manifest.json',PLACES]
    paths.extend(sorted((ROOT/'frozen_backend').rglob('*.py')))
    paths.extend(sorted((ROOT/'frozen_analytics').rglob('*.py')))
    hashes={str(p):sha(p) for p in paths}
    value={'rules':RULES,'rules_sha256':frozen.digest(RULES),'code_sha256':sha(__file__),'frozen_before_holdout_outcomes':False,'frozen_before_corrected_replay_outcomes':True,'retrieval_bug_fix_after_prior_diagnostic_outcomes':True}
    if (ROOT/'community-frozen-rules.json').exists():
        assert json.loads((ROOT/'community-frozen-rules.json').read_text())==value,'Frozen Rule C changed'
    else:save('community-frozen-rules.json',value)
    if (ROOT/'community-input-manifest.json').exists():
        assert json.loads((ROOT/'community-input-manifest.json').read_text())==hashes,'Frozen Rule C inputs changed'
    else:save('community-input-manifest.json',hashes)
    return hashes


class Communities:
    def __init__(self, places):
        self.catalog=alias_module.RegistryLocationIndex(places)
        labels=collections.defaultdict(set)
        for p in places:labels[str(p.get('area_label') or '')].add(_area_key(p.get('area_key')))
        self.names={_area_key(p.get('area_label')):str(p.get('area_label')) for p in places if p.get('area_label') and ((_area_key(p.get('building_key'))==_area_key(p.get('area_label')) and int(p.get('match_rank') or 0)==2) or _area_key(p.get('area_label')) not in labels[str(p['area_label'])])}
        self.normalized={alias_module._geo.normalize_location_name(name):key for key,name in self.names.items()}
        self.target_cache={}
        self.legal_members=collections.defaultdict(set)
        self.place_members=collections.defaultdict(list)
        for p in places:
            community=self.canonical(p.get('area_label'))
            if not community:continue
            for area in (p.get('area_key'),p.get('area_label')):
                if area:self.legal_members[_area_key(area)].add(community)
            for name in (p.get('building_label'),p.get('project_label'),p.get('building_key')):
                if name:self.place_members[_place_key(name)].append((community,_area_key(p.get('area_key')),_area_key(p.get('area_label')),_place_key(p.get('project_label'))))

    def canonical(self,value):
        return self.normalized.get(alias_module._geo.normalize_location_name(str(value or '')))

    def source(self,row):
        s=row['source'];evidence=[];keys=set()
        # Raw master_project is original spreadsheet evidence. Neither filename
        # nor a parser-generated area alone supplies independent scope.
        original=[('raw_fields',row.get('raw_fields',{})),('raw_location_fields',s.get('raw_location_fields',{}))]
        for origin,data in original:
            for field in ('area_name','master_project','master_project_name','project_name','building_name'):
                value=str(data.get(field) or '').strip()
                if not tm.identifier(value):continue
                key=self.canonical(value)
                method='exact_original_community'
                if not key and field in ('project_name','master_project','master_project_name'):
                    # The qualifying community must occupy an entire leading
                    # component; no arbitrary substring or suffix stripping.
                    leading=re.split(r'\s+[-:]\s+',value,maxsplit=1)[0]
                    key=self.canonical(leading)
                    method='original_qualified_community_prefix'
                if key:
                    keys.add(key);evidence.append({'origin':origin,'field':field,'value':value,'method':method,'community':key})
        normalized=self.canonical(s.get('area_name'))
        if len(keys)!=1:return None,{'reason':'missing_or_conflicting_explicit_catalog_community','original_evidence':evidence}
        key=next(iter(keys))
        if normalized and normalized!=key:return None,{'reason':'normalized_community_conflicts_original','original_evidence':evidence}
        return key,{'community':key,'community_name':self.names[key],'original_evidence':evidence,'filename_used':False}

    def memberships(self,target):
        signature=tuple(str(target.get(f) or '') for f in ('area_name','project_name','building_name','building_key','area_key','location_name'))
        if signature in self.target_cache:return self.target_cache[signature]
        legal={_area_key(target.get(f)) for f in ('area_name','area_key') if target.get(f)}
        direct={self.canonical(target.get(f)) for f in ('area_name','project_name','building_name')}-{None}
        scoped=set()
        project=_place_key(target.get('project_name'))
        for field in ('building_name','project_name','building_key'):
            value=str(target.get(field) or '')
            if not value or c1_identifier_numeric(value):continue
            if field!='project_name' and tm.generic_building(value) and not project:continue
            for community,a,b,p in self.place_members.get(_place_key(value),()):
                if legal and not (legal & {a,b}):continue
                if field!='project_name' and project and p and project!=p:continue
                scoped.add(community)
        named=direct|scoped
        possible_legal=set().union(*(self.legal_members.get(a,set()) for a in legal)) if legal else set()
        definite=named if len(named)==1 else set()
        possible=named if definite else named|possible_legal
        raw_areas=[str(target.get(f) or '') for f in ('area_name','area_key')]
        if not possible and all(not tm.identifier(v) or _area_key(v) in {'dubai','uae'} for v in raw_areas):possible={'__unscoped__'}
        result={'definite':sorted(definite),'possible':sorted(possible),'ambiguous':len(possible)>1 or not definite,'explicit_named_communities':sorted(direct),'catalog_scoped_communities':sorted(scoped),'legal_area_possible_communities':sorted(possible_legal)}
        self.target_cache[signature]=result
        return result

    def target(self,target):
        definite=self.memberships(target)['definite']
        return definite[0] if len(definite)==1 else None


def c1_identifier_numeric(value):
    return tm.identifier(str(value)).isdigit()


def physical_kind(value):
    kind=tm._kind(value)
    if kind:return kind
    compact=re.sub(r'[^a-z]','',str(value or '').lower())
    return 'plot' if compact in ('commercialplot','commercialplots','residentialplot','residentialplots') else ''


def source_frame(row):
    s={**row['source'],'raw_fields':row.get('raw_fields',{}),'source_event_id':row.get('source_event_id'),'source_unit_id':row.get('source_unit_id'),'_declared_size_unit':row.get('source_declared_size_unit','unknown')}
    for f in ('area_name','project_name','building_name'):
        if not tm.identifier(str(s.get(f) or '')):s[f]=''
    # Original numbered/generic labels remain constraints even when they cannot
    # independently establish geography. Only literal missing values blank above.
    return s


def location_id_leaks(row):
    ids=[tm.identifier(v['value']) for v in fields(row,ALL_IDS) if v['origin']!='normalized' and re.search(r'\d',v['value'])]
    locations=[]
    for origin,data in [('source',row['source']),('raw_fields',row.get('raw_fields',{})),('raw_location_fields',row['source'].get('raw_location_fields',{}))]:
        for field in ('building_name','project_name'):
            value=str(data.get(field) or '')
            if not tm.identifier(value):continue
            key=tm.identifier(value);compact=_place_key(value)
            leaked=False
            for code in ids:
                codecompact=_place_key(code)
                if len(codecompact)>=3 and any(c.isalpha() for c in codecompact) and codecompact in compact:leaked=True
                if code.isdigit() and (key==code or code in {str(int(n)) for n in re.findall(r'\d+',value)}):leaked=True
            if re.search(r'(?i)(?:[a-z]+[- ]v[- ]?\d+|r3.*?[- ]v[- ]?\d+|dh2[-_]|(?:villa|unit|flat|apt)\s*[-:#]?\s*\d+)',value):leaked=True
            if leaked:locations.append(origin+'.'+field)
    return sorted(set(locations))


def masked_row(row):
    result={**row,'source':frozen.masked(row['source'])}
    result['raw_fields']={k:v for k,v in row.get('raw_fields',{}).items() if k not in {*frozen.IDENTIFIER_FIELDS,'land_number','land_sub_number','municipality_number','municipality_sub_number'}}
    return result


class Index:
    def __init__(self,path):
        self.path=Path(path)
        self.db=sqlite3.connect(str(path));self.db.execute('PRAGMA cache_size=-32768')
        self.db.execute('PRAGMA temp_store=FILE')

    def build(self,snapshot,communities,needed):
        self.db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT)')
        prior=dict(self.db.execute('SELECT key,value FROM metadata'))
        expected={'snapshot_path':str(snapshot),'snapshot_size':str(snapshot.stat().st_size),'snapshot_mtime':str(snapshot.stat().st_mtime_ns),'rules':frozen.digest(RULES),'code':sha(__file__),'places':sha(PLACES)}
        if prior:
            assert all(prior.get(k)==v for k,v in expected.items()) and prior.get('complete')=='true','Incompatible private community index'
            targets={key:json.loads(p) for key,p in self.db.execute('SELECT event_key,payload FROM baseline_target')}
            return targets,{'reused':True,'sale_events_scanned':int(prior['sale_events_scanned']),'indexed_records':int(prior['indexed_records'])}
        self.db.execute('CREATE TABLE sale(event_rowid INTEGER, amount REAL, community TEXT, day TEXT, size REAL, payload TEXT)')
        self.db.execute('CREATE TABLE baseline_target(event_key TEXT PRIMARY KEY,payload TEXT)')
        source=sqlite3.connect('file:'+str(snapshot)+'?mode=ro&immutable=1',uri=True);source.execute('PRAGMA query_only=ON')
        targets={};buffer=[];scanned=0;indexed=0
        for rowid,payload in source.execute("SELECT rowid,payload FROM event WHERE family='sale'"):
            target=json.loads(payload);scanned+=1;event_key=frozen.ek(target)
            if event_key in needed:targets[event_key]=target
            membership=communities.memberships(target)
            if membership['possible']:
                safe={k:target.get(k) for k in SAFE_TARGET if k in target}
                date=frozen.day(target.get('transaction_date'));size=tm.positive_decimal(target.get('size_sqft'))
                safe['_community_membership']=membership
                compact=json.dumps(safe,separators=(',',':'),default=str)
                for community in membership['possible']:
                    for amount in {a for _,a in tm._amounts(target)}:
                        buffer.append((rowid,float(amount),community,str(date) if date else None,float(size) if size else None,compact));indexed+=1
            if len(buffer)>=5000:self.db.executemany('INSERT INTO sale VALUES(?,?,?,?,?,?)',buffer);buffer=[]
            if scanned%200000==0:print(json.dumps({'checkpoint':'community_index','sale_events_scanned':scanned,'indexed_records':indexed}),flush=True)
        if buffer:self.db.executemany('INSERT INTO sale VALUES(?,?,?,?,?,?)',buffer)
        self.db.executemany('INSERT INTO baseline_target VALUES(?,?)',[(k,json.dumps(t,separators=(',',':'))) for k,t in targets.items()])
        self.db.execute('CREATE INDEX community_day_amount ON sale(community,day,amount)')
        self.db.execute('CREATE INDEX community_amount_day ON sale(community,amount,day)')
        self.db.executemany('INSERT INTO metadata VALUES(?,?)',list({**expected,'complete':'true','sale_events_scanned':str(scanned),'indexed_records':str(indexed)}.items()));self.db.commit()
        assert source.total_changes==0
        return targets,{'reused':False,'sale_events_scanned':scanned,'indexed_records':indexed,'snapshot_writes':source.total_changes}

    def query(self,community,amount,date,near=False):
        lo=float(amount-Decimal(2));hi=float(amount+Decimal(2));eps=max(abs(lo),abs(hi),1)*2e-15
        if near:
            sql="SELECT payload FROM sale WHERE community IN (?,'__unscoped__') AND amount BETWEEN ? AND ? AND (day IS NULL OR day BETWEEN ? AND ?)"
            args=(community,lo-eps,hi+eps,str(date-timedelta(days=14)),str(date+timedelta(days=14)))
        else:
            sql="SELECT payload FROM sale WHERE community IN (?,'__unscoped__') AND day=? AND amount BETWEEN ? AND ?"
            args=(community,str(date),lo-eps,hi+eps)
        seen=set()
        for payload, in self.db.execute(sql,args):
            target=json.loads(payload)
            if not any(abs(value-amount)<=Decimal(2) for _,value in tm._amounts(target)):continue
            key=(frozen.ek(target),frozen.prop(target))
            if key not in seen:
                seen.add(key)
                membership=target.get('_community_membership')
                if membership is not None:target['_community_positive_evidence']=membership['definite']==[community]
                yield target


def candidate_detail(source,target,aliases,size):
    detail=aliases.features(source,target)
    conflicts=list(detail['location']['conflicts'])
    observed=tm.identifier(str(target.get('unit_number') or ''))
    kind=physical_kind(source.get('property_type')) or physical_kind(target.get('property_type'))
    roles={'flat':('unit_number','property_number'),'villa':('unit_number','building_number'),'plot':('unit_number','plot_number','plot_pre_reg_number','property_number')}.get(kind,('unit_number',))
    parents={a['source_field'] for a in detail['learned_aliases'] if a['kind']=='parent' and a['accepted']}
    explicit=[v for v in fields(source,ALL_IDS) if v['origin']!='normalized' and tm.identifier(v['value']) and v['field'] in roles and v['field'] not in parents]
    for v in explicit:
        if tm.identifier(v['value'])!=observed:conflicts.append('original_child_id_conflict:'+v['field'])
    target_size=tm.positive_decimal(target.get('size_sqft'))
    compatible=bool(physical_kind(source.get('property_type')) and physical_kind(source.get('property_type'))==physical_kind(target.get('property_type')))
    if target.get('_community_positive_evidence') is False:conflicts.append('ambiguous_community_membership_rival_only')
    ok=compatible and not conflicts and not tm.physical_types_conflict(source.get('property_type'),target.get('property_type')) and bool(size and target_size and tm.sizes_match(size,target_size)) and bool(all(frozen.prop(target)[1:]))
    return ok,{'conflicts':sorted(set(conflicts)),'target_size_sqft':str(target_size) if target_size else None,'explicit_child_fields':sorted({v['field'] for v in explicit}),'learned_parent_fields':sorted(parents)}


def target_summary(target):
    return {'event_key':frozen.ek(target),'property':list(frozen.prop(target)),'target':{k:target.get(k) for k in SAFE_TARGET if k not in ('building_key','area_key','location_name')}}


def select(row,index,communities,aliases,sizes):
    result={'row_key':row.get('row_key'),'source_event_id':row.get('source_event_id'),'source_unit_id':row.get('source_unit_id'),'primary_cause':row.get('primary_cause'),'profile':PROFILE,'status':'unresolved','reason':'missing_fingerprint','selected':None,'candidate_pool_uncapped':True}
    s=source_frame(row);community,scope=communities.source(row);result['community_evidence']=scope
    if s.get('event_family')!='sale':result['reason']='source_not_explicit_sale';return result
    if not physical_kind(s.get('property_type')):result['reason']='unknown_source_physical_type';return result
    if row.get('primary_cause')=='original_address_codes_contradict':result['reason']='original_address_contradiction_retained';return result
    if not community:result['reason']=scope['reason'];return result
    amount=tm.positive_decimal(s.get('amount_aed'));date=frozen.day(s.get('transaction_date'))
    size,size_evidence=frozen.source_size(s,sizes);result['size_evidence']=size_evidence
    if not amount or not date or not size:result['reason']='missing_positive_amount_exact_day_or_independent_size';return result
    exact=[];excluded=collections.Counter();exact_count=0
    for target in index.query(community,amount,date):
        exact_count+=1;ok,detail=candidate_detail(s,target,aliases,size)
        if ok:exact.append((target,detail))
        else:
            for conflict in detail['conflicts']:excluded[conflict]+=1
    result['exactday_amount_community_events']=exact_count;result['exactday_candidate_count']=len(exact);result['exactday_rejections']=dict(excluded)
    if len(exact)!=1 or len({frozen.prop(t) for t,d in exact})!=1:
        result['reason']='no_complete_joint_fingerprint' if not exact else 'multiple_exactday_fingerprint_events_or_properties'
        result['exactday_examples']=[target_summary(t) for t,d in exact[:5]];return result
    target,detail=exact[0];competitors=[];count=0
    for rival in index.query(community,amount,date,near=True):
        if frozen.ek(rival)==frozen.ek(target) and frozen.prop(rival)==frozen.prop(target):continue
        rival_kind=physical_kind(rival.get('property_type'))
        if rival_kind and rival_kind!=physical_kind(s.get('property_type')):continue
        if tm.physical_types_conflict(s.get('property_type'),rival.get('property_type')):continue
        rival_size=tm.positive_decimal(rival.get('size_sqft'))
        if rival_size and not tm.sizes_match(size,rival_size):continue
        count+=1
        if len(competitors)<5:competitors.append(target_summary(rival))
    result['selected']=target_summary(target);result['candidate_evidence']=detail;result['near_competitor_count']=count;result['near_competitors']=competitors;result['near_competitors_display_truncated']=max(0,count-5)
    if count:result['reason']='nearby_or_undated_same_community_price_size_competitor';return result
    result['status']='conditional_rule_c_candidate';result['reason']='unique_joint_community_price_exactday_independent_size';result['proposed_only_missing_identifier']=str(target.get('unit_number') or '')
    return result


def run(args):
    os.umask(0o077);started=time.time();before=freeze();places=json.loads(PLACES.read_text());communities=Communities(places)
    baseline={};baseline_rows=[]
    for line in (ROOT/'baseline-matched.jsonl').open():
        row=json.loads(line);baseline[row['source_event_id']]=row;baseline_rows.append(row)
    needed={frozen.current_key(r) for r in baseline_rows}
    index=Index(ROOT/'community-index.sqlite');targets,index_summary=index.build(args.snapshot,communities,needed)
    baseline_targets=[(r,targets[frozen.current_key(r)]) for r in baseline_rows if frozen.current_key(r) in targets]
    assert len(baseline_targets)==len(baseline_rows),'Missing baseline targets'
    pairs=[]
    for row in baseline.values():
        target=targets.get(frozen.current_key(row))
        if target is not None and not row['current_match'].get('flags') and qualified(row['source'],target):pairs.append((row,target))
    split=frozen.dsu_split(pairs);train=[(r,t) for r,t in pairs if split[r['source_event_id']]=='train'];test=[(r,t) for r,t in pairs if split[r['source_event_id']]=='test']
    prior=[json.loads(line) for line in (ROOT/'engine-training-pairs.jsonl').open()]
    assert {(r['source_event_id'],frozen.ek(t)) for r,t in train}=={(p['source_event_id'],frozen.ek(p['target'])) for p in prior},'Frozen TRAIN split changed'
    assert not {frozen.prop(t) for r,t in train}&{frozen.prop(t) for r,t in test}
    assert not {r['source_unit_id'] for r,t in train}&{r['source_unit_id'] for r,t in test}
    sizes=SheetSizeEvidence()
    for r,t in train:sizes.observe(r['source'],[(t,200,[])])
    aliases=AliasModel([{'source':{**r['source'],'source_event_id':r['source_event_id'],'source_unit_id':r['source_unit_id'],'raw_fields':r.get('raw_fields',{})},'target':t} for r,t in train],places=places)
    save('community-training-summary.json',{'weak_pairs':len(pairs),'train_pairs':len(train),'holdout_pairs':len(test),'train_split_identical_to_frozen_engine':True,'rules_sha256':frozen.digest(RULES),'index':index_summary})
    counts=collections.Counter();categories=collections.defaultdict(collections.Counter);examples={};proposals=[];rows=0
    with (ROOT/'community-results.pre-veto.jsonl').open('w') as out:
        for line in (ROOT/'rows.jsonl').open():
            row=json.loads(line);rows+=1
            if frozen.current_live(row):
                result={'row_key':row['row_key'],'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'primary_cause':row['primary_cause'],'profile':PROFILE,'status':'already_live_recovered','reason':'matched_before_conditional_profile','selected':None}
            else:result=select(row,index,communities,aliases,sizes)
            if result['status']=='conditional_rule_c_candidate':proposals.append((row,result))
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
            if result['reason'] not in examples:examples[result['reason']]={'source':{k:row['source'].get(k) for k in ('area_name','project_name','building_name','amount_aed','transaction_date','size_sqft','size_unknown','property_type')},**result}
            if rows%5000==0:print(json.dumps({'checkpoint':'community_focus','rows':rows,'elapsed_seconds':round(time.time()-started)}),flush=True)
    assert rows==sum(frozen.CAUSES.values())==36102
    temporary=[(r,{**x,'status':'new_supported_inferred'}) for r,x in proposals]
    focus_reuse=frozen.veto(temporary,[],baseline_targets)
    bad_rows={r['row_key'] for r,x in temporary if x['status']!='new_supported_inferred'}
    example_rows={value['row_key']:key for key,value in examples.items()}
    with (ROOT/'community-results.jsonl').open('w') as out:
        for line in (ROOT/'community-results.pre-veto.jsonl').open():
            result=json.loads(line)
            if result['row_key'] in bad_rows:result.update(status='unresolved',reason='global_source_property_or_event_reuse_conflict')
            if result['row_key'] in example_rows:
                key=example_rows[result['row_key']];examples[key]={**examples[key],**result}
            counts[result['status']]+=1;categories[result['primary_cause']][result['status']]+=1
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    hold=collections.Counter();leaks=collections.Counter();evaluated=[];excluded=[]
    for row,target in test:
        leakage=location_id_leaks(row);hold['weak_pairs']+=1
        if leakage:
            hold['excluded_location_identifier_leakage']+=1;leaks.update(leakage)
            excluded.append({'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'status':'excluded_location_identifier_leakage','leakage_fields':leakage})
        else:
            hold['evaluated_masked_pairs']+=1;masked=masked_row(row)
            evaluated.append((masked,target,select(masked,index,communities,aliases,sizes)))
    temporary=[(r,{**x,'status':'new_supported_inferred'}) for r,t,x in evaluated if x['status']=='conditional_rule_c_candidate']
    holdout_reuse=frozen.veto(temporary,[],train)
    bad_holdout={r['source_event_id'] for r,x in temporary if x['status']!='new_supported_inferred'}
    with (ROOT/'community-holdout.jsonl').open('w') as out:
        for result in excluded:out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
        for row,target,result in evaluated:
            if row['source_event_id'] in bad_holdout:result.update(status='unresolved',reason='global_source_property_or_event_reuse_conflict')
            hold[result['status']]+=1
            if result['status']=='conditional_rule_c_candidate':
                hold['selected']+=1;hold['same_event_agreement']+=int(result['selected']['event_key']==frozen.ek(target));hold['same_property_agreement']+=int(tuple(result['selected']['property'])==frozen.prop(target));hold['different_property_collision']+=int(tuple(result['selected']['property'])!=frozen.prop(target))
            result.update(weak_event=frozen.ek(target),weak_property=list(frozen.prop(target)))
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    after={p:sha(p) for p in before};assert before==after,'Frozen Rule C inputs changed'
    summary={'check':'PASS','profile':PROFILE,'conditional_only':True,'focus_rows':rows,'statuses':dict(counts),'by_category':dict(categories),'holdout':dict(hold),'holdout_leakage_fields':dict(leaks),'training':{'pairs':len(train),'disjoint_holdout_pairs':len(test)},'focus_reuse':focus_reuse,'holdout_reuse':holdout_reuse,'focus_baseline_reference_rows':len(baseline_targets),'outside_five_groups_touched':0,'snapshot_writes':0,'rules_sha256':frozen.digest(RULES),'code_sha256':sha(__file__),'inputs_unchanged':True,'elapsed_seconds':round(time.time()-started),'limitations':['Conditional candidates are separate from conservative main-profile recovery.','Deduplicate row_key against main results before reporting conditional additional rows.','Masked weak-label agreement is not match precision or ownership evidence.']}
    save('community-examples.json',examples);save('community-summary.json',summary);print(json.dumps(summary,sort_keys=True,default=str),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot',type=Path,default=SNAPSHOT);parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    if args.freeze_only:freeze();print(json.dumps({'frozen':True,'rules_sha256':frozen.digest(RULES),'code_sha256':sha(__file__)}))
    else:run(args)
