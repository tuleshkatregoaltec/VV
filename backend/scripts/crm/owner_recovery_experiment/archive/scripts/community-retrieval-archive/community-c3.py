"""Prospectively declared C3 size-hypothesis profile, separate from frozen C1."""
import argparse
import collections
import importlib.util
import json
import os
import time
from decimal import Decimal
from pathlib import Path
import community_fingerprint as c1

ROOT=Path(__file__).parent
PROFILE='community_joint_fingerprint_size_hypotheses_generic_type'
RULES={**c1.RULES,'version':'community-joint-fingerprint-C3','conditional_only':True,'size':'Use C1 independently known/TRAIN-learned size when available. Otherwise enumerate raw size_unknown as sqft and sqm; candidate must have known size within max(50sqft,2%) of at least one interpretation. Require unique event/property across the UNION of both interpretations. Nearby/unknown-date competitors veto if size matches EITHER interpretation or is unknown.','assumption_tier':'Candidate-dependent size interpretation is a higher-assumption conditional proposal, never independently learned unit proof.','declaration_timing':'Exploratory profile frozen after C1 and C2 aggregate outcomes, before ANY C3 results; same weak-label holdout is diagnostic, not independent validation.','physical_type':'Explicit source Residential/Building/Unit supplies NO physical-form discriminator. Permit recognized target forms as conditional assumptions; retain ALL other forms and unknown-type competitors. Specific source Flat/Villa/Land kinds must agree with target. Preserve raw broad label and report assumed target form, never physical corroboration.'}
STATUS='conditional_rule_c3_candidate'


def save(name,value):c1.save('community-c3-'+name,value)


def freeze():
    paths=[Path(__file__),ROOT/'community_fingerprint.py',ROOT/'community-frozen-rules.json',ROOT/'community-input-manifest.json',ROOT/'community-summary.json',ROOT/'community-c2.py',ROOT/'community-c2-summary.json',ROOT/'community-c2-frozen-rules.json',ROOT/'community-index.sqlite',ROOT/'engine.py',ROOT/'aliases.py',ROOT/'rows.jsonl',ROOT/'baseline-matched.jsonl',ROOT/'engine-training-pairs.jsonl',c1.PLACES]
    paths.extend(sorted((ROOT/'frozen_backend').rglob('*.py')));paths.extend(sorted((ROOT/'frozen_analytics').rglob('*.py')))
    hashes={str(p):c1.sha(p) for p in paths}
    declaration={'rules':RULES,'rules_sha256':c1.frozen.digest(RULES),'code_sha256':c1.sha(__file__),'frozen_before_C3_outcomes':True,'C1_C2_aggregate_metrics_already_seen':True}
    for name,value in [('frozen-rules.json',declaration),('input-manifest.json',hashes)]:
        path=ROOT/('community-c3-'+name)
        if path.exists():assert json.loads(path.read_text())==value,'Frozen C3 changed'
        else:save(name,value)
    return hashes


def hypotheses(source,sizes):
    size,evidence=c1.frozen.source_size(source,sizes)
    if size:return [('independent_source',size)],{**evidence,'candidate_dependent':False}
    raw=c1.tm.positive_decimal(source.get('size_unknown'))
    if not raw:return [],{**evidence,'candidate_dependent':False}
    values=[('sqft',raw),('sqm',raw*c1.frozen.SQM_TO_SQFT)]
    return values,{'basis':'candidate_dependent_sqft_or_sqm_hypotheses','candidate_dependent':True,'raw':str(raw),'hypotheses':{label:str(value) for label,value in values},'independently_learned_unit':False}


def broad_type(value):
    return str(value or '').strip().lower() in {'residential','building','unit'}


def candidate_detail(source,target,aliases,size):
    if not broad_type(source.get('property_type')):
        ok,detail=c1.candidate_detail(source,target,aliases,size)
        return ok,{**detail,'generic_source_type_no_physical_discriminator':False,'raw_source_property_type':source.get('property_type')}
    detail=aliases.features(source,target)
    conflicts=list(detail['location']['conflicts'])
    observed=c1.tm.identifier(str(target.get('unit_number') or ''))
    # Unknown physical form gives no license to ignore an original child code.
    # Any possible child field must agree unless independent baseline evidence
    # establishes that field as a parent at this target building.
    parents={a['source_field'] for a in detail['learned_aliases'] if a['kind']=='parent' and a['accepted']}
    roles=set(c1.frozen.IDENTIFIER_FIELDS)
    explicit=[v for v in c1.fields(source,c1.ALL_IDS) if v['origin']!='normalized' and c1.tm.identifier(v['value']) and v['field'] in roles and v['field'] not in parents]
    for v in explicit:
        if c1.tm.identifier(v['value'])!=observed:conflicts.append('possible_original_child_id_conflict:'+v['field'])
    target_size=c1.tm.positive_decimal(target.get('size_sqft'))
    ok=bool(c1.physical_kind(target.get('property_type'))) and not conflicts and bool(size and target_size and c1.tm.sizes_match(size,target_size)) and bool(all(c1.frozen.prop(target)[1:]))
    return ok,{'conflicts':sorted(set(conflicts)),'target_size_sqft':str(target_size) if target_size else None,'explicit_child_fields':sorted({v['field'] for v in explicit}),'learned_parent_fields':sorted(parents),'raw_source_property_type':source.get('property_type'),'generic_source_type_no_physical_discriminator':True,'assumed_target_physical_form':c1.physical_kind(target.get('property_type')),'physical_type_corroboration':False}


def select(row,index,communities,aliases,sizes):
    result={'row_key':row.get('row_key'),'source_event_id':row.get('source_event_id'),'source_unit_id':row.get('source_unit_id'),'primary_cause':row.get('primary_cause'),'profile':PROFILE,'status':'unresolved','reason':'missing_fingerprint','selected':None,'candidate_pool_uncapped':True}
    s=c1.source_frame(row);community,scope=communities.source(row);result['community_evidence']=scope
    if s.get('event_family')!='sale':result['reason']='source_not_explicit_sale';return result
    if not c1.physical_kind(s.get('property_type')) and not broad_type(s.get('property_type')):result['reason']='unknown_source_physical_type';return result
    if row.get('primary_cause')=='original_address_codes_contradict':result['reason']='original_address_contradiction_retained';return result
    if not community:result['reason']=scope['reason'];return result
    amount=c1.tm.positive_decimal(s.get('amount_aed'));day=c1.frozen.day(s.get('transaction_date'));sizes_to_try,evidence=hypotheses(s,sizes);result['size_evidence']=evidence
    if not amount or not day or not sizes_to_try:result['reason']='missing_positive_amount_exact_day_or_raw_size';return result
    exact=[];excluded=collections.Counter();count=0
    for target in index.query(community,amount,day):
        count+=1;fits=[];detail=None
        for label,size in sizes_to_try:
            ok,detail=candidate_detail(s,target,aliases,size)
            if ok:fits.append(label)
        if fits:exact.append((target,detail,fits))
        else:
            for conflict in detail['conflicts']:excluded[conflict]+=1
    result['exactday_amount_community_events']=count;result['exactday_candidate_count']=len(exact);result['exactday_rejections']=dict(excluded)
    if len(exact)!=1 or len({c1.frozen.prop(t) for t,d,f in exact})!=1:
        result['reason']='no_complete_joint_fingerprint' if not exact else 'multiple_events_or_properties_across_size_hypotheses_generic_type';result['exactday_examples']=[{**c1.target_summary(t),'size_hypotheses_generic_type':fits} for t,d,fits in exact[:5]];return result
    target,detail,fits=exact[0];competitors=[];count=0
    for rival in index.query(community,amount,day,near=True):
        if c1.frozen.ek(rival)==c1.frozen.ek(target) and c1.frozen.prop(rival)==c1.frozen.prop(target):continue
        kind=c1.physical_kind(rival.get('property_type'))
        if not broad_type(s.get('property_type')) and kind and kind!=c1.physical_kind(s.get('property_type')):continue
        if c1.tm.physical_types_conflict(s.get('property_type'),rival.get('property_type')):continue
        size=c1.tm.positive_decimal(rival.get('size_sqft'))
        if size and not any(c1.tm.sizes_match(value,size) for label,value in sizes_to_try):continue
        count+=1
        if len(competitors)<5:competitors.append(c1.target_summary(rival))
    result.update(selected=c1.target_summary(target),candidate_evidence=detail,selected_size_hypotheses=fits,near_competitor_count=count,near_competitors=competitors,near_competitors_display_truncated=max(0,count-5))
    if count:result['reason']='nearby_or_undated_competitor_under_either_size_hypothesis';return result
    result.update(status=STATUS,reason='unique_joint_fingerprint_union_of_size_hypotheses_generic_type',proposed_only_missing_identifier=str(target.get('unit_number') or ''),assumption_tier=('generic_source_type_no_physical_discriminator' + ('+candidate_dependent_size_unit' if evidence['candidate_dependent'] else '')) if broad_type(s.get('property_type')) else ('candidate_dependent_size_unit' if evidence['candidate_dependent'] else 'independent_source_size'))
    return result


def run():
    os.umask(0o077);started=time.time();before=freeze();places=json.loads(c1.PLACES.read_text());communities=c1.Communities(places)
    index=c1.Index(ROOT/'community-index.sqlite');targets={key:json.loads(payload) for key,payload in index.db.execute('SELECT event_key,payload FROM baseline_target')}
    baseline={};baseline_rows=[]
    for line in (ROOT/'baseline-matched.jsonl').open():
        row=json.loads(line);baseline[row['source_event_id']]=row;baseline_rows.append(row)
    baseline_targets=[(r,targets[c1.frozen.current_key(r)]) for r in baseline_rows if c1.frozen.current_key(r) in targets];assert len(baseline_targets)==len(baseline_rows)
    pairs=[(r,targets[c1.frozen.current_key(r)]) for r in baseline.values() if c1.frozen.current_key(r) in targets and not r['current_match'].get('flags') and c1.qualified(r['source'],targets[c1.frozen.current_key(r)])]
    split=c1.frozen.dsu_split(pairs);train=[(r,t) for r,t in pairs if split[r['source_event_id']]=='train'];test=[(r,t) for r,t in pairs if split[r['source_event_id']]=='test']
    prior=[json.loads(line) for line in (ROOT/'engine-training-pairs.jsonl').open()];assert {(r['source_event_id'],c1.frozen.ek(t)) for r,t in train}=={(p['source_event_id'],c1.frozen.ek(p['target'])) for p in prior}
    assert not {c1.frozen.prop(t) for r,t in train}&{c1.frozen.prop(t) for r,t in test};assert not {r['source_unit_id'] for r,t in train}&{r['source_unit_id'] for r,t in test}
    sizes=c1.SheetSizeEvidence()
    for r,t in train:sizes.observe(r['source'],[(t,200,[])])
    aliases=c1.AliasModel([{'source':{**r['source'],'source_unit_id':r['source_unit_id'],'source_event_id':r['source_event_id'],'raw_fields':r.get('raw_fields',{})},'target':t} for r,t in train],places=places)
    proposals=[];n=0
    with (ROOT/'community-c3-results.pre-veto.jsonl').open('w') as out:
        for line in (ROOT/'rows.jsonl').open():
            row=json.loads(line);n+=1
            if c1.frozen.current_live(row):result={'row_key':row['row_key'],'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'primary_cause':row['primary_cause'],'profile':PROFILE,'status':'already_live_recovered','reason':'matched_before_conditional_profile','selected':None}
            else:result=select(row,index,communities,aliases,sizes)
            if result['status']==STATUS:proposals.append((row,result))
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    assert n==36102
    temporary=[(r,{**x,'status':'new_supported_inferred'}) for r,x in proposals];focus_reuse=c1.frozen.veto(temporary,[],baseline_targets);bad={r['row_key'] for r,x in temporary if x['status']!='new_supported_inferred'}
    counts=collections.Counter();reasons=collections.Counter();tiers=collections.Counter();categories=collections.defaultdict(collections.Counter)
    with (ROOT/'community-c3-results.jsonl').open('w') as out:
        for line in (ROOT/'community-c3-results.pre-veto.jsonl').open():
            result=json.loads(line)
            if result['row_key'] in bad:result.update(status='unresolved',reason='global_source_property_or_event_reuse_conflict')
            counts[result['status']]+=1;reasons[result['reason']]+=1;categories[result['primary_cause']][result['status']]+=1
            if result['status']==STATUS:tiers[result['assumption_tier']]+=1
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    evaluated=[];excluded=[];hold=collections.Counter();leaks=collections.Counter()
    for row,target in test:
        hold['weak_pairs']+=1;leakage=c1.location_id_leaks(row)
        if leakage:
            hold['excluded_location_identifier_leakage']+=1;leaks.update(leakage);excluded.append({'source_event_id':row['source_event_id'],'source_unit_id':row['source_unit_id'],'status':'excluded_location_identifier_leakage','leakage_fields':leakage})
        else:
            hold['evaluated_masked_pairs']+=1;masked=c1.masked_row(row);evaluated.append((masked,target,select(masked,index,communities,aliases,sizes)))
    temporary=[(r,{**x,'status':'new_supported_inferred'}) for r,t,x in evaluated if x['status']==STATUS];holdout_reuse=c1.frozen.veto(temporary,[],train);bad={r['source_event_id'] for r,x in temporary if x['status']!='new_supported_inferred'}
    with (ROOT/'community-c3-holdout.jsonl').open('w') as out:
        for result in excluded:out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
        for row,target,result in evaluated:
            if row['source_event_id'] in bad:result.update(status='unresolved',reason='global_source_property_or_event_reuse_conflict')
            hold[result['status']]+=1
            if result['status']==STATUS:
                hold['selected']+=1;hold['same_event_agreement']+=int(result['selected']['event_key']==c1.frozen.ek(target));hold['same_property_agreement']+=int(tuple(result['selected']['property'])==c1.frozen.prop(target));hold['different_property_collision']+=int(tuple(result['selected']['property'])!=c1.frozen.prop(target));hold['candidate_dependent_size_selected']+=int(result['size_evidence']['candidate_dependent'])
            result.update(weak_event=c1.frozen.ek(target),weak_property=list(c1.frozen.prop(target)));out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    assert before=={p:c1.sha(p) for p in before},'C3 input changed'
    summary={'check':'PASS','profile':PROFILE,'conditional_only':True,'focus_rows':n,'statuses':dict(counts),'reasons':dict(reasons),'assumption_tiers':dict(tiers),'by_category':dict(categories),'holdout':dict(hold),'holdout_leakage_fields':dict(leaks),'focus_reuse':focus_reuse,'holdout_reuse':holdout_reuse,'focus_baseline_reference_rows':len(baseline_targets),'training':{'pairs':len(train),'disjoint_holdout_pairs':len(test)},'code_sha256':c1.sha(__file__),'rules_sha256':c1.frozen.digest(RULES),'inputs_unchanged':True,'outside_five_groups_touched':0,'snapshot_writes':0,'declaration_timing':'Exploratory after C1 and C2 aggregate outcomes; before C3 outcomes','elapsed_seconds':round(time.time()-started)}
    save('summary.json',summary);print(json.dumps(summary,sort_keys=True),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    if args.freeze_only:freeze();print(json.dumps({'frozen_C3':True,'code_sha256':c1.sha(__file__),'rules_sha256':c1.frozen.digest(RULES)}))
    else:run()
