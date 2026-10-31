"""Read only sanitized frames/catalog and immutable snapshot; write alias evidence only."""
import collections
import hashlib
import json
import sqlite3
from pathlib import Path
from aliases import AliasModel, fields, _codes, _frame, _place_key, identifier

ROOT = Path(__file__).parent
INPUT = Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded')

def main():
    places = json.loads((INPUT / 'places-snapshot.json').read_text())
    raw_roles = collections.Counter()
    afmu = []
    parents = collections.defaultdict(set)
    for line in (ROOT / 'all-rows.jsonl').open():
        row = json.loads(line)
        original = fields(row, ('unit_number', 'property_number', 'building_number', 'plot_number'))
        for v in original:
            if v['origin'] != 'normalized':
                raw_roles[v['field']] += 1
        for field, code in _codes(row):
            if field in ('plot_number', 'property_number'):
                children = {code for field, code in _codes(row) if field == 'unit_number'}
                parents[(field, code)].update(children - {code})
            if code == 'afmu19b':
                afmu.append({'source_unit_id': row.get('source_unit_id'), 'source_event_id': row.get('source_event_id'), 'source_field': field, 'source_value': next((v['value'] for v in original if v['field'] == field), ''), 'area_name': _frame(row).get('area_name'), 'project_name': _frame(row).get('project_name'), 'property_type': _frame(row).get('property_type')})
    afmu = list({(v['source_event_id'], v['source_field'], v['source_value']): v for v in afmu}.values())
    focus_ids = {json.loads(line)['source_event_id'] for line in (ROOT / 'rows.jsonl').open()}
    conn = sqlite3.connect(f'file:{INPUT / "snapshot.sqlite"}?mode=ro&immutable=1', uri=True)
    conn.execute('PRAGMA query_only=ON')
    target_fields = {'unit_number', 'area_name', 'project_name', 'building_name', 'property_type', 'size_sqft', 'building_key', 'area_key'}
    targets = [{k: v for k, v in json.loads(payload).items() if k in target_fields} for payload, in conn.execute("SELECT payload FROM event WHERE rowid IN (SELECT event_rowid FROM property_lookup WHERE identifier='afmu19b')")]
    model = AliasModel(places=places)
    checks = []
    # Use the exact row frame; source values remain confined to property fields.
    for line in (ROOT / 'all-rows.jsonl').open():
        row = json.loads(line)
        if any(code == 'afmu19b' for _, code in _codes(row)):
            for target in targets:
                d = model.qualify(row, target)
                checks.append({'source_unit_id': row.get('source_unit_id'), 'target_unit_number': target['unit_number'], 'qualified_property_evidence_only': d['qualified'], 'identifier_strength': d['identifier']['strength'], 'location_strength': d['location']['strength'], 'evidence': d['evidence'], 'conflicts': d['location']['conflicts'] + d['identifier']['conflicts']})
    catalog = [{k: p.get(k) for k in ('location_id', 'area_key', 'area_label', 'project_label', 'building_label', 'building_key')} for p in places if _place_key(p.get('building_key')) == 'alfurjan']
    trained = ROOT / 'engine-alias-training-audit.json'
    training = json.loads(trained.read_text()) if trained.exists() else []
    report = {'original_field_records': dict(raw_roles), 'source_codes_with_multiple_explicit_child_units': {field: sum(f == field and len(units) > 1 for (f, code), units in parents.items()) for field in ('property_number', 'plot_number')}, 'parent_role_examples': [{'field': field, 'code': code, 'distinct_explicit_child_units': len(units)} for (field, code), units in sorted(parents.items(), key=lambda x: (-len(x[1]), x[0]))[:15]], 'afmu019b': {'outside_five_group_cohort': not any(v['source_event_id'] in focus_ids for v in afmu), 'diagnostic_property_example_only': True, 'source_property_fields': afmu, 'dxbi_property_context': targets, 'dxbi_catalog_area_evidence': catalog, 'helper_checks': checks, 'snapshot_writes': conn.total_changes}, 'learned_alias_coverage': {'audit_available': trained.exists(), 'groups': len(training), 'accepted_groups': sum(a['accepted'] for a in training), 'accepted_by_kind': dict(collections.Counter(a['kind'] for a in training if a['accepted'])), 'all_accepted_heldout_supported': all(a['heldout_unit_support'] for a in training if a['accepted']), 'training_audit_sha256': hashlib.sha256(trained.read_bytes()).hexdigest() if trained.exists() else None}, 'not_transaction_match_counts': True}
    (ROOT / 'alias-role-evidence.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'source_codes_with_multiple_explicit_child_units': report['source_codes_with_multiple_explicit_child_units'], 'afmu019b_source_property_records': len(afmu), 'afmu019b_dxbi_events': len(targets), 'afmu019b_full_property_evidence_checks': len(checks), 'afmu019b_checks_pass': all(c['qualified_property_evidence_only'] for c in checks), 'learned_alias_coverage': report['learned_alias_coverage'], 'snapshot_writes': conn.total_changes}))

if __name__ == '__main__':
    main()
