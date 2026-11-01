"""Join conditional profiles by row key; preserve profile provenance and veto union reuse."""
import collections
import json
from pathlib import Path
import community_fingerprint as c

ROOT=Path(__file__).parent
PROFILES=[('C1','community'),('C2','community-c2'),('C3','community-c3'),('C4','community-c4'),('C5_exact','community-c5-exact'),('C5_history','community-c5-history')]


def conditional(result):return str(result.get('status') or '').startswith('conditional_') and str(result['status']).endswith('_candidate')


def compact(row):
    return {'row_key':row.get('row_key'),'source_event_id':row.get('source_event_id'),'source_unit_id':row.get('source_unit_id'),'source':{'original_identifiers':row['source'].get('original_identifiers',{}),'building_name':row['source'].get('building_name')}}


def main():
    summaries={label:json.loads((ROOT/(prefix+'-summary.json')).read_text()) for label,prefix in PROFILES}
    files=[(ROOT/(prefix+'-results.jsonl')).open() for label,prefix in PROFILES]
    overlapping=collections.Counter();proposal_keys=set();rows=0
    with (ROOT/'community-combined-pre-veto.jsonl').open('w') as out:
        for lines in zip(*files,strict=True):
            values=[json.loads(line) for line in lines];keys={v['row_key'] for v in values};assert len(keys)==1
            options=[(label,v) for (label,prefix),v in zip(PROFILES,values) if conditional(v)]
            for label,value in options:overlapping[label]+=1
            if options:label,result=options[0];result={**result};proposal_keys.add(result['row_key'])
            else:
                label,result=PROFILES[-1][0],values[-1]
                # An exact-day unresolved candidate displays the useful bulk-
                # registration conflict; it is never promoted by display order.
                if not values[-1].get('community_repair') and values[-2].get('selected') and values[-2].get('near_competitor_count',0):label,result=PROFILES[-2][0],values[-2]
                result={**result}
            result['profile_reasons']={name:v.get('reason') for (name,prefix),v in zip(PROFILES,values)}
            result['community_repair_applied']=bool(result.get('community_repair'))
            result['latest_tested_profile']='C5_history'
            result['latest_tested_reason']=values[-1].get('reason')
            original_status=result['status'];result.update(original_profile_status=original_status,original_profile=result.get('profile'),conditional_profile=label if options else None,profile_priority=next(i+1 for i,(name,prefix) in enumerate(PROFILES) if name==label),profile_rules_sha256=summaries[label]['rules_sha256'],profile_code_sha256=summaries[label]['code_sha256'],overlapping_profiles=[name for name,value in options],all_profile_outcomes={name:{'status':v['status'],'reason':v.get('reason')} for (name,prefix),v in zip(PROFILES,values)})
            flags=[]
            if result.get('community_repair'):flags.append('systematic_source_community_label_repair')
            if result.get('size_evidence',{}).get('candidate_dependent'):flags.append('candidate_dependent_size_unit')
            if result.get('candidate_evidence',{}).get('generic_source_type_no_physical_discriminator'):flags.append('generic_type_supplies_no_physical_discriminator')
            if result.get('date_is_not_selector'):flags.append('date_relaxed_entire_history_uniqueness')
            if label!='C1':flags.append('exploratory_reused_weak_label_holdout')
            result['assumption_flags']=flags
            if options:result['status']='conditional_rule_c_candidate'
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n');rows+=1
    assert rows==36102
    for file in files:file.close()
    proposals={}
    for line in (ROOT/'community-combined-pre-veto.jsonl').open():
        value=json.loads(line)
        if value['row_key'] in proposal_keys:proposals[value['row_key']]=value
    sources={};all_source_examples={}
    for line in (ROOT/'rows.jsonl').open():
        row=json.loads(line)
        if row['row_key'] in proposals:sources[row['row_key']]=compact(row)
    index=c.Index(ROOT/'community-index.sqlite');targets={key:json.loads(payload) for key,payload in index.db.execute('SELECT event_key,payload FROM baseline_target')}
    baseline=[]
    for line in (ROOT/'baseline-matched.jsonl').open():
        row=json.loads(line);baseline.append((compact(row),targets[c.frozen.current_key(row)]))
    assert len(baseline)==44414
    temporary=[(sources[key],{**result,'status':'new_supported_inferred'}) for key,result in proposals.items()]
    conflicts=c.frozen.veto(temporary,[],baseline);bad={r['row_key'] for r,x in temporary if x['status']!='new_supported_inferred'}
    main_status={}
    if (ROOT/'metrics.json').exists() and (ROOT/'results.jsonl').exists():
        assert json.loads((ROOT/'metrics.json').read_text())['check']=='PASS'
        main_status={r['row_key']:r['status'] for line in (ROOT/'results.jsonl').open() if (r:=json.loads(line))}
        assert len(main_status)==36102
    counts=collections.Counter();incremental=collections.Counter();additional=collections.Counter();reasons=collections.Counter();selected_units=set();events=set();properties=set();repaired=0;example_keys={}
    with (ROOT/'community-combined-results.jsonl').open('w') as out:
        for line in (ROOT/'community-combined-pre-veto.jsonl').open():
            result=json.loads(line)
            if result['row_key'] in bad:result.update(status='unresolved',reason='combined_profiles_global_source_property_or_event_reuse_conflict')
            result['main_priority_status']=main_status.get(result['row_key'])
            result['additional_to_main']=result['status']=='conditional_rule_c_candidate' and result['main_priority_status'] not in ('new_supported_inferred','already_live_recovered') if main_status else None
            counts[result['status']]+=1;reasons[result['reason']]+=1
            if result['status']=='conditional_rule_c_candidate':
                incremental[result['conditional_profile']]+=1
                if result['additional_to_main']:additional[result['conditional_profile']]+=1
                selected_units.add(result['source_unit_id']);events.add(result['selected']['event_key']);properties.add(tuple(result['selected']['property']));repaired+=bool(result.get('community_repair'))
            example_type=('conditional_'+str(result['conditional_profile'])) if result['status']=='conditional_rule_c_candidate' else result['reason']
            if example_type not in example_keys:example_keys[example_type]=result['row_key']
            out.write(json.dumps(result,sort_keys=True,default=str)+'\n')
    wanted=set(example_keys.values());result_examples={}
    for line in (ROOT/'community-combined-results.jsonl').open():
        result=json.loads(line)
        if result['row_key'] in wanted:result_examples[result['row_key']]=result
    examples=[]
    for line in (ROOT/'rows.jsonl').open():
        row=json.loads(line)
        if row['row_key'] not in wanted:continue
        result=result_examples[row['row_key']]
        safe_source={k:row['source'].get(k) for k in ('area_name','project_name','building_name','property_type','amount_aed','transaction_date','size_unknown','size_sqft','original_identifiers')}
        safe_raw={k:v for k,v in row.get('raw_fields',{}).items() if k in {'master_project','area_name','project_name','building_name',*c.ALL_IDS}}
        examples.append({'filename':row['filename'],'sheet':row['sheet'],'row':row['row'],'original_source_property_fields':safe_source,'original_raw_property_fields':safe_raw,'comparison':result})
    c.save('community-side-by-side.json',examples)
    summary={'check':'PASS','rows':rows,'priority':[name for name,prefix in PROFILES],'statuses':dict(counts),'overlapping_candidate_counts':{name:overlapping[name] for name,prefix in PROFILES},'incremental_priority_counts':{name:incremental[name] for name,prefix in PROFILES},'union_conditional_rows':sum(incremental.values()),'union_distinct_source_units':len(selected_units),'union_distinct_events':len(events),'union_distinct_properties':len(properties),'union_repaired_rows':repaired,'conditional_additional_to_main_counts':{name:additional[name] for name,prefix in PROFILES} if main_status else None,'main_comparison_complete':bool(main_status),'union_reuse_veto':conflicts,'union_vetoed_rows':len(bad),'reasons':dict(reasons),'per_profile_holdout':{name:s['holdout'] for name,s in summaries.items()},'profile_metadata':{name:{k:s[k] for k in ('code_sha256','rules_sha256','profile','conditional_only')} for name,s in summaries.items()},'snapshot_writes':0,'outside_five_groups_touched':0,'limitations':['All conditional profiles remain separate from conservative main recovery.','C2-C5 and corrected retrieval replays reuse observed diagnostic weak-label outcomes; agreement is not independent precision.','Systematic source-label repair preserves raw values and is a conditional proposal.']}
    c.save('community-combined-summary.json',summary);print(json.dumps(summary,sort_keys=True),flush=True)

if __name__=='__main__':main()
