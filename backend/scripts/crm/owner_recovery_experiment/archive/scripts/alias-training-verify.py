"""Rebuild alias crosswalk from frozen train pairs only and expose its support."""
import collections
import hashlib
import json
from pathlib import Path
from aliases import AliasModel

ROOT = Path(__file__).parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    source = ROOT / 'engine-training-pairs.jsonl'
    pairs = [json.loads(line) for line in source.open()]
    places = json.loads(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json').read_text())
    model = AliasModel(pairs, places=places)
    audit = model.audit()
    crosswalk = []
    for a, (key, records) in zip(audit, sorted(model.groups.items())):
        assert a['kind'] == key[0] and a['source_key'] == key[3]
        destinations = collections.Counter(d for _, _, d in set(records))
        crosswalk.append({**a, 'target_locations': [{'area_key': d[0], 'project_key': d[1], 'building_key': d[2], 'distinct_source_registry_pairs': n} for d, n in sorted(destinations.items())], 'support_source_unit_ids': sorted({s for s, _, _ in records}), 'support_registry_unit_keys': [list(t) for t in sorted({t for _, t, _ in records})]})
    accepted = [a for a in crosswalk if a['accepted']]
    assert all(a['scope'] and a['distinct_destinations'] == 1 and a['distinct_registry_units'] >= 3 and a['heldout_unit_support'] for a in accepted)
    assert all(not a['scope'].startswith('building_name::') for a in accepted if a['kind'] == 'parent')
    summary = {'training_pairs': len(pairs), 'accepted_role_correct_baseline_rows': model.training_rows, 'rejected_anchor_rows': model.rejected_training_rows, 'alias_groups': len(audit), 'accepted_alias_groups': len(accepted), 'accepted_by_kind': dict(collections.Counter(a['kind'] for a in accepted)), 'mixed_destination_groups_rejected': sum(a['distinct_destinations'] > 1 and not a['accepted'] for a in audit), 'blank_scoped_groups': sum(not a['scope'] for a in audit), 'query_unit_excluded_in_features': True, 'baseline_train_pairs_sha256': sha(source), 'aliases_sha256': sha(ROOT / 'aliases.py'), 'alias_support_is_not_match_precision': True}
    (ROOT / 'alias-learned-crosswalk.json').write_text(json.dumps({'summary': summary, 'crosswalk': crosswalk}, indent=2, sort_keys=True) + '\n')
    print(json.dumps(summary, sort_keys=True))

if __name__ == '__main__':
    main()
