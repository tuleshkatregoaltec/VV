"""Targeted, auditable autofill-label repair; conditional exact/history profiles."""
import argparse
import collections
import importlib.util
import json
import os
import re
import time
from pathlib import Path
import community_fingerprint as c1

ROOT=Path(__file__).parent

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/file);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
c3=module('community_repair_c3','community-c3.py');c4=module('community_repair_c4','community-c4.py')
RULES={'version':'community-autofill-repair-C5.1-retrieval2','conditional_only':True,'sequence':'Original raw master_project numeric suffix must advance exactly +1 for at least10 strictly contiguous source rows, fixed prefix and suffix-row offset; derived from source-only all-rows, not targets.','community':'Frozen TRAIN-only file/sheet context needs >=10 distinct physical properties AND source units, 100% one independently catalog-validated canonical community, matching source/canonical nonnumeric prefix. Exclude query source unit and candidate target physical property.','preservation':'Repair query COPY only when original label has no valid catalog community, normalized source area agrees with corrupt label or is blank, and no source location field names a different valid community. Preserve original raw/master labels and all precise subcommunity/building fields. No raw ID edits.','matching':'After repair apply unchanged C3 exact-date or C4 whole-history uniqueness, dual size hypotheses, broad types supply no discriminator, full child/location conflict gates, all unknown/compatible rivals and global reuse veto.','scope':'Write only the original five-group focus36102 rows; outside-group source rows can establish arithmetic sequence but are never rematched or modified.','holdout':'Same frozen property/source-component split, TRAIN-only evidence; masked location-ID leak exclusion; diagnostic exploratory reused weak-label holdout after C1-C4 aggregate outcomes. Report repaired holdout subset separately.','profiles':{'exact':c3.RULES,'history':c4.RULES}}


def save(name,value):c1.save('community-c5-'+name,value)


def freeze():
    paths=[Path(__file__),ROOT/'all-rows.jsonl',ROOT/'rows.jsonl',ROOT/'baseline-matched.jsonl',ROOT/'engine-training-pairs.jsonl',ROOT/'community_fingerprint.py',ROOT/'community-c3.py',ROOT/'community-c4.py',ROOT/'community-c3-frozen-rules.json',ROOT/'community-c4-frozen-rules.json',ROOT/'community-c3-summary.json',ROOT/'community-c4-summary.json',ROOT/'label-sequence-evidence.json',ROOT/'engine.py',ROOT/'aliases.py',ROOT/'community-index.sqlite',c1.PLACES]
    paths.extend(sorted((ROOT/'frozen_backend').rglob('*.py')));paths.extend(sorted((ROOT/'frozen_analytics').rglob('*.py')))
    hashes={str(p):c1.sha(p) for p in paths}
    declaration={'rules':RULES,'rules_sha256':c1.frozen.digest(RULES),'code_sha256':c1.sha(__file__),'frozen_before_C5_outcomes':False,'frozen_before_corrected_replay_outcomes':True,'retrieval_bug_fix_after_prior_diagnostic_outcomes':True,'C1_C4_aggregate_outcomes_already_seen':True}
    for name,value in [('frozen-rules.json',declaration),('input-manifest.json',hashes)]:
        path=ROOT/('community-c5-'+name)
        if path.exists():assert json.loads(path.read_text())==value,'Frozen C5 changed'
        else:save(name,value)
    return hashes


def basename(value):return re.split(r'[/\\]',str(value or ''))[-1]


def label(value):
    match=re.fullmatch(r'(.*?\D)\s*(\d+)\s*',str(value or '').strip())
    return (c1._place_key(match[1]),int(match[2])) if match else None


class Repair:
    def __init__(self,rows,train,communities):
        self.communities=communities;self.blocks={};self.contexts=collections.defaultdict(set)
        grouped=collections.defaultdict(list)
        for row in rows:
            original=str(row.get('raw_fields',{}).get('master_project') or '')
            parsed=label(original)
            if parsed and row.get('row') is not None:
                grouped[(basename(row['filename']),str(row['sheet']),parsed[0])].append((int(row['row']),parsed[1],row['row_key'],original))
        for key,entries in grouped.items():
            entries.sort();current=[]
            def finish():
                if len(current)<10:return
                block={'filename':key[0],'sheet':key[1],'prefix_key':key[2],'first_row':current[0][0],'last_row':current[-1][0],'rows':len(current),'suffix_minus_row':current[0][1]-current[0][0],'all_adjacent_source_rows_increment_suffix_by_one':True}
                for number,suffix,row_key,original in current:self.blocks[row_key]={**block,'source_row':number,'original_suffix':suffix,'original_label':original}
            for entry in entries:
                if current and (entry[0]!=current[-1][0]+1 or entry[1]!=current[-1][1]+1):finish();current=[]
                current.append(entry)
            finish()
        for row,target in train:
            source=row['source'];key=(basename(source.get('source_filename') or row.get('filename')),str(source.get('source_sheet') or row.get('sheet') or ''))
            community=communities.target(target)
            self.contexts[key].add((str(row['source_unit_id']),c1.frozen.prop(target),community or '__unknown_catalog_community__'))

    def support(self,row,target=None):
        key=(basename(row.get('filename') or row['source'].get('source_filename')),str(row.get('sheet') or row['source'].get('source_sheet') or ''))
        uid=str(row.get('source_unit_id') or '')
        excluded_property=c1.frozen.prop(target) if target is not None else None
        retained={(u,p,c) for u,p,c in self.contexts.get(key,()) if u!=uid and p!=excluded_property}
        communities={c for u,p,c in retained};properties={p for u,p,c in retained};units={u for u,p,c in retained}
        known_pure=len(communities)==1 and '__unknown_catalog_community__' not in communities
        accepted=known_pure and len(properties)>=10 and len(units)>=10
        return {'accepted':accepted,'canonical_community':next(iter(communities)) if known_pure else None,'independent_properties':len(properties),'independent_source_units':len(units),'distinct_communities':len(communities),'community_purity':'1' if known_pure else None,'unknown_community_properties':len({p for u,p,c in retained if c=='__unknown_catalog_community__'}),'query_source_unit_excluded':True,'candidate_target_property_excluded':target is not None,'baseline_TRAIN_only':True}

    def apply(self,row):
        block=self.blocks.get(row.get('row_key'))
        if not block:return row,None
        original=str(row.get('raw_fields',{}).get('master_project') or '')
        if original!=block['original_label'] or self.communities.canonical(original):return row,None
        support=self.support(row)
        if not support['accepted']:return row,None
        community=support['canonical_community'];canonical_name=self.communities.names[community];canonical=label(canonical_name)
        if not canonical or canonical[0]!=block['prefix_key']:return row,None
        s=row['source'];source_area=str(s.get('area_name') or '')
        if source_area and c1._place_key(source_area)!=c1._place_key(original):return row,None
        for origin,data in [('normalized_source',s),('raw_fields',row.get('raw_fields',{})),('raw_location_fields',s.get('raw_location_fields',{}))]:
            for field in ('area_name','project_name','building_name','master_project','master_project_name'):
                value=str(data.get(field) or '')
                existing=self.communities.canonical(value) or self.communities.canonical(re.split(r'\s+[-:]\s+',value,maxsplit=1)[0])
                if existing and existing!=community:return row,None
        repaired_source={**s};changed={}
        repaired_source['area_name']=canonical_name;changed['area_name']={'original':source_area,'proposed':canonical_name}
        for field in ('project_name','building_name'):
            if c1._place_key(s.get(field))==c1._place_key(original):
                changed[field]={'original':s.get(field),'proposed':canonical_name};repaired_source[field]=canonical_name
        evidence={'method':'source_contiguous_autofill_sequence_plus_independent_TRAIN_sheet_community','original_raw_master_project':original,'proposed_community':community,'proposed_community_name':canonical_name,'sequence':block,'training_support':support,'normalized_query_fields_only':changed,'raw_fields_preserved':True,'not_filename_name_guess':True,'conditional_repair_assumption':True}
        return {**row,'source':repaired_source,'_community_repair':evidence},evidence

    def audit(self):
        unique={tuple((k,v) for k,v in b.items() if k not in ('source_row','original_suffix','original_label')) for b in self.blocks.values()}
        contexts=[]
        for key,records in sorted(self.contexts.items()):
            contexts.append({'filename':key[0],'sheet':key[1],'distinct_physical_properties':len({p for u,p,c in records}),'distinct_source_units':len({u for u,p,c in records}),'canonical_communities':sorted({c for u,p,c in records}),'unknown_community_properties':len({p for u,p,c in records if c=='__unknown_catalog_community__'}),'baseline_TRAIN_only':True})
        return {'sequence_rows':len(self.blocks),'sequence_blocks':[dict(v) for v in sorted(unique)],'TRAIN_sheet_contexts':contexts}


class RepairedCommunities:
    def __init__(self,base):self.base=base
    def source(self,row):
        evidence=row.get('_community_repair')
        if evidence:return evidence['proposed_community'],{'community':evidence['proposed_community'],'community_name':evidence['proposed_community_name'],'repair_evidence':evidence,'filename_used_as_name_guess':False}
        return self.base.source(row)


def select(row,index,communities,aliases,sizes,repair,mode):
    copied,evidence=repair.apply(row)
    result=(c3.select if mode=='exact' else c4.select)(copied,index,RepairedCommunities(communities),aliases,sizes)
    if evidence:
        result['community_repair']=evidence
        if result['selected']:
            selected=result['selected']['target'];support=repair.support(row,selected)
            result['community_repair']['candidate_excluded_training_support']=support
            if not support['accepted'] or support['canonical_community']!=evidence['proposed_community']:
                result.update(status='unresolved',reason='community_repair_insufficient_support_after_candidate_property_exclusion')
    expected=c3.STATUS if mode=='exact' else c4.STATUS
    if result['status']==expected:
        result['status']='conditional_rule_c5_'+mode+'_candidate'
        result['assumption_tier']=result.get('assumption_tier','')+('+source_autofill_community_repair' if evidence else '')
    result['profile']='community_autofill_repair_'+mode
    return result


def evaluate(mode,index,communities,aliases,sizes,repair,train,test,baseline_targets):
    status='conditional_rule_c5_'+mode+'_candidate';prefix='community-c5-'+mode;proposals=[];repaired_rows=0;rows=0
    with (ROOT/(prefix+'-results.pre-veto.jsonl')).open('w') as out:
        for line in (ROOT/'rows.jsonl').open():
            row=json.loads(line);rows+=1
            if c1.frozen.current_live(row):result={'row_key':row['row_key'],'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'primary_cause':row['primary_cause'],'profile':'community_autofill_repair_'+mode,'status':'already_live_recovered','reason':'matched_before_conditional_profile','selected':None}
            else:result=select(row,index,communities,aliases,sizes,repair,mode)
            repaired_rows+=bool(result.get('community_repair'))
            if result['status']==status:proposals.append((row,result))
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    temporary=[(r,{**x,'status':'new_supported_inferred'}) for r,x in proposals];focus_reuse=c1.frozen.veto(temporary,[],baseline_targets);bad={r['row_key'] for r,x in temporary if x['status']!='new_supported_inferred'}
    counts=collections.Counter();reasons=collections.Counter();categories=collections.defaultdict(collections.Counter);repairs=collections.Counter()
    with (ROOT/(prefix+'-results.jsonl')).open('w') as out:
        for line in (ROOT/(prefix+'-results.pre-veto.jsonl')).open():
            result=json.loads(line)
            if result['row_key'] in bad:result.update(status='unresolved',reason='global_source_property_or_event_reuse_conflict')
            counts[result['status']]+=1;reasons[result['reason']]+=1;categories[result['primary_cause']][result['status']]+=1
            if result.get('community_repair'):repairs[result['status']]+=1
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    evaluated=[];excluded=[];hold=collections.Counter();leaks=collections.Counter()
    for row,target in test:
        hold['weak_pairs']+=1;leakage=c1.location_id_leaks(row)
        if leakage:
            hold['excluded_location_identifier_leakage']+=1;leaks.update(leakage);excluded.append({'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'status':'excluded_location_identifier_leakage','leakage_fields':leakage})
        else:
            hold['evaluated_masked_pairs']+=1;masked=c1.masked_row(row);result=select(masked,index,communities,aliases,sizes,repair,mode);evaluated.append((masked,target,result));hold['repaired_masked_rows']+=bool(result.get('community_repair'))
    temporary=[(r,{**x,'status':'new_supported_inferred'}) for r,t,x in evaluated if x['status']==status];holdout_reuse=c1.frozen.veto(temporary,[],train);bad={r['source_event_id'] for r,x in temporary if x['status']!='new_supported_inferred'}
    with (ROOT/(prefix+'-holdout.jsonl')).open('w') as out:
        for result in excluded:out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
        for row,target,result in evaluated:
            if row['source_event_id'] in bad:result.update(status='unresolved',reason='global_source_property_or_event_reuse_conflict')
            hold[result['status']]+=1
            if result['status']==status:
                same_event=result['selected']['event_key']==c1.frozen.ek(target);same_property=tuple(result['selected']['property'])==c1.frozen.prop(target)
                hold['selected']+=1;hold['same_event_agreement']+=same_event;hold['same_property_agreement']+=same_property;hold['different_property_collision']+=not same_property
                if result.get('community_repair'):hold['repaired_selected']+=1;hold['repaired_same_property_agreement']+=same_property
            result.update(weak_event=c1.frozen.ek(target),weak_property=list(c1.frozen.prop(target)));out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    assert rows==36102
    summary={'check':'PASS','profile':'community_autofill_repair_'+mode,'conditional_only':True,'focus_rows':rows,'statuses':dict(counts),'reasons':dict(reasons),'by_category':dict(categories),'repaired_query_rows':repaired_rows,'repaired_statuses':dict(repairs),'holdout':dict(hold),'holdout_leakage_fields':dict(leaks),'focus_reuse':focus_reuse,'holdout_reuse':holdout_reuse,'focus_baseline_reference_rows':len(baseline_targets),'training':{'pairs':len(train),'disjoint_holdout_pairs':len(test)},'code_sha256':c1.sha(__file__),'rules_sha256':c1.frozen.digest(RULES),'outside_five_groups_touched':0,'snapshot_writes':0,'declaration_timing':'Exploratory after C1-C4 outcomes; before C5 outcomes'}
    c1.save(prefix+'-summary.json',summary);return summary


def run():
    os.umask(0o077);started=time.time();before=freeze();places=json.loads(c1.PLACES.read_text());communities=c1.Communities(places);index=c1.Index(ROOT/'community-index.sqlite')
    targets={key:json.loads(payload) for key,payload in index.db.execute('SELECT event_key,payload FROM baseline_target')};baseline={};baseline_rows=[]
    for line in (ROOT/'baseline-matched.jsonl').open():
        row=json.loads(line);baseline[row['source_event_id']]=row;baseline_rows.append(row)
    baseline_targets=[(r,targets[c1.frozen.current_key(r)]) for r in baseline_rows if c1.frozen.current_key(r) in targets];assert len(baseline_targets)==len(baseline_rows)
    pairs=[(r,targets[c1.frozen.current_key(r)]) for r in baseline.values() if c1.frozen.current_key(r) in targets and not r['current_match'].get('flags') and c1.qualified(r['source'],targets[c1.frozen.current_key(r)])]
    split=c1.frozen.dsu_split(pairs);train=[(r,t) for r,t in pairs if split[r['source_event_id']]=='train'];test=[(r,t) for r,t in pairs if split[r['source_event_id']]=='test'];prior=[json.loads(line) for line in (ROOT/'engine-training-pairs.jsonl').open()]
    assert {(r['source_event_id'],c1.frozen.ek(t)) for r,t in train}=={(p['source_event_id'],c1.frozen.ek(p['target'])) for p in prior}
    assert not {c1.frozen.prop(t) for r,t in train}&{c1.frozen.prop(t) for r,t in test};assert not {r['source_unit_id'] for r,t in train}&{r['source_unit_id'] for r,t in test}
    sizes=c1.SheetSizeEvidence()
    for r,t in train:sizes.observe(r['source'],[(t,200,[])])
    aliases=c1.AliasModel([{'source':{**r['source'],'source_unit_id':r['source_unit_id'],'source_event_id':r['source_event_id'],'raw_fields':r.get('raw_fields',{})},'target':t} for r,t in train],places=places)
    repair=Repair((json.loads(line) for line in (ROOT/'all-rows.jsonl').open()),train,communities);save('repair-evidence.json',repair.audit())
    summaries={mode:evaluate(mode,index,communities,aliases,sizes,repair,train,test,baseline_targets) for mode in ('exact','history')}
    assert before=={p:c1.sha(p) for p in before},'C5 inputs changed'
    save('summary.json',{'check':'PASS','profiles':summaries,'inputs_unchanged':True,'elapsed_seconds':round(time.time()-started),'rules_sha256':c1.frozen.digest(RULES),'code_sha256':c1.sha(__file__)});print(json.dumps({'check':'PASS','profiles':summaries,'elapsed_seconds':round(time.time()-started)},sort_keys=True),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    if args.freeze_only:freeze();print(json.dumps({'frozen_C5':True,'code_sha256':c1.sha(__file__),'rules_sha256':c1.frozen.digest(RULES)}))
    else:run()
