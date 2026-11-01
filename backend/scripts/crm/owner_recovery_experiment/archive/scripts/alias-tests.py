import json
import unittest
from pathlib import Path
from aliases import AliasModel

PLACES = json.loads(Path('/tmp/vv-owner-corpus-2026-10-28/unit-guarded/places-snapshot.json').read_text())


def source(unit='AFMU019B', **kwargs):
    frame = {'area_name': 'Al Furjan', 'project_name': 'Al Furjan West', 'property_type': 'Commercial Plots', **kwargs}
    return {'source_unit_id': unit, 'source': frame, 'raw_fields': {'property_number': unit, 'unit_number': '', **kwargs}}


def target(unit='AFMU019B', **kwargs):
    return {'area_name': 'Jabal Ali 1', 'building_name': 'Al Furjan', 'project_name': '', 'property_type': 'Plot', 'unit_number': unit, **kwargs}


class EvidenceTests(unittest.TestCase):
    def test_afmu_full_code_role_with_dxbi_area_bridge(self):
        detail = AliasModel(places=PLACES).qualify(source(), target())
        self.assertTrue(detail['qualified'])
        self.assertIn('property_number_plot_full_code_role_reinterpretation', detail['evidence'])
        self.assertEqual(detail['location']['strength'], 'parent')

    def test_target_cache_preserves_property_type_role(self):
        model = AliasModel(places=PLACES)
        self.assertTrue(model.qualify(source(), target())['qualified'])
        self.assertFalse(model.qualify(source(), target(property_type='Apartment'))['qualified'])

    def test_afmu_bad_suffix_is_never_child(self):
        detail = AliasModel(places=PLACES).qualify(source(), target('019B'))
        self.assertFalse(detail['qualified'])
        self.assertNotEqual(detail['identifier']['scope'], 'child')

    def test_conflicting_full_codes_veto(self):
        detail = AliasModel(places=PLACES).qualify(source(unit_number='OTHER019B'), target())
        self.assertTrue(detail['conflict'])
        self.assertFalse(detail['qualified'])

    def test_wrong_community_veto(self):
        self.assertFalse(AliasModel(places=PLACES).qualify(source(area_name='Dubai Marina'), target())['qualified'])

    def test_numbered_building_suffix_veto(self):
        s = {'area_name': 'Dubai Marina', 'building_name': 'Tower 1', 'unit_number': '101'}
        t = {'area_name': 'Dubai Marina', 'building_name': 'Tower 2', 'unit_number': '101'}
        self.assertTrue(AliasModel().qualify(s, t)['conflict'])

    def test_explicit_wrong_building_cannot_hide_behind_shared_project(self):
        s = {'area_name': 'Dubai Marina', 'project_name': 'Project', 'building_name': 'Alpha', 'unit_number': '101'}
        t = {'area_name': 'Dubai Marina', 'project_name': 'Project', 'building_name': 'Beta', 'unit_number': '101'}
        self.assertTrue(AliasModel().qualify(s, t)['conflict'])

    def test_explicit_wrong_subcommunity_cannot_hide_behind_building(self):
        s = {'area_name': 'Arabian Ranches 3', 'project_name': 'Joy', 'building_name': 'Sun', 'unit_number': '101'}
        t = {'area_name': 'Arabian Ranches 3', 'project_name': 'Sun', 'building_name': 'Sun', 'unit_number': '101'}
        self.assertTrue(AliasModel().qualify(s, t)['conflict'])

    def training(self, count=3, mixed=False):
        pairs = []
        for n in range(count):
            s = {'source_unit_id': f's{n}', 'source': {'area_name': 'Dubai Marina', 'building_name': 'Old Tower', 'unit_number': str(101+n)}, 'raw_fields': {'unit_number': str(101+n), 'plot_number': 'PARENT001'}}
            t = {'area_name': 'Dubai Marina', 'project_name': 'Project', 'building_name': 'New Tower' if not mixed or n < 2 else 'Other Tower', 'unit_number': str(101+n)}
            pairs.append({'source': s, 'target': t})
        return pairs

    def test_shared_parent_cannot_become_child(self):
        model = AliasModel(self.training())
        s = {'source_unit_id': 'new', 'source': {'area_name': 'Dubai Marina'}, 'raw_fields': {'plot_number': 'PARENT001'}}
        t = {'area_name': 'Dubai Marina', 'project_name': 'Project', 'building_name': 'New Tower', 'unit_number': 'PARENT001'}
        d = model.qualify(s, t)
        self.assertFalse(d['qualified'])
        self.assertEqual(d['identifier']['scope'], 'parent')
        self.assertIn('shared_parent_never_child', d['evidence'])

    def test_query_unit_and_source_unit_removed(self):
        pairs = self.training()
        model = AliasModel(pairs)
        d = model.features(pairs[0]['source'], pairs[0]['target'])
        audits = d['learned_aliases']
        self.assertTrue(audits)
        self.assertTrue(all(a['independent_registry_units'] == 2 for a in audits))
        self.assertTrue(all(a['independent_source_units'] == 2 for a in audits))
        self.assertTrue(all(a['query_unit_excluded'] for a in audits))

    def test_duplicate_transactions_are_no_independent_unit_support(self):
        pair = self.training(1)[0]
        model = AliasModel([pair] * 10)
        self.assertTrue(all(not a['accepted'] for a in model.audit()))

    def test_no_learning_from_inferred_property_role_or_suffix(self):
        pairs = self.training()
        for p in pairs:
            p['source']['raw_fields']['unit_number'] = ''
            p['source']['source']['unit_number'] = ''
            p['source']['raw_fields']['property_number'] = p['target']['unit_number']
        model = AliasModel(pairs)
        self.assertEqual(model.training_rows, 0)

    def test_generated_unit_cannot_train_alias(self):
        pairs = self.training()
        for p in pairs:
            p['source']['raw_fields']['unit_number'] = ''
        self.assertEqual(AliasModel(pairs).training_rows, 0)

    def test_original_villa_building_fullcode_can_train_without_unit(self):
        pairs = self.training()
        for n, p in enumerate(pairs):
            code = f'VILLA{n+1}'
            p['source']['raw_fields']['unit_number'] = ''
            p['source']['raw_fields']['building_number'] = code
            p['source']['source']['unit_number'] = str(n+1)
            p['source']['source']['property_type'] = 'Villa'
            p['target']['unit_number'] = code
            p['target']['property_type'] = 'Villa'
        self.assertEqual(AliasModel(pairs).training_rows, 3)

    def test_original_flat_property_identifier_can_train(self):
        pairs = self.training()
        for p in pairs:
            p['source']['raw_fields']['unit_number'] = ''
            p['source']['raw_fields']['property_number'] = p['target']['unit_number']
            p['source']['source']['property_type'] = 'Apartment'
            p['target']['property_type'] = 'Apartment'
        self.assertEqual(AliasModel(pairs).training_rows, 3)

    def test_learned_alias_does_not_erase_building_suffix(self):
        pairs = self.training()
        for p in pairs:
            p['source']['raw_fields']['building_name'] = 'Old Tower 1'
        self.assertFalse(any(a['kind'] == 'building' for a in AliasModel(pairs).audit()))

    def test_wrong_role_cannot_become_unit(self):
        s = {'area_name': 'Dubai Marina', 'building_name': 'Tower 1', 'land_number': '101'}
        t = {'area_name': 'Dubai Marina', 'building_name': 'Tower 1', 'property_type': 'Apartment', 'unit_number': '101'}
        self.assertFalse(AliasModel().qualify(s, t)['qualified'])

    def test_blank_location_parent_alias_cannot_learn(self):
        pairs = self.training()
        for p in pairs:
            p['source']['source'] = {'unit_number': p['target']['unit_number']}
        self.assertEqual(AliasModel(pairs).audit(), [])

    def test_parent_needs_community_or_project_not_only_building(self):
        pairs = self.training()
        for p in pairs:
            p['source']['source'].pop('area_name')
        self.assertFalse(any(a['kind'] == 'parent' for a in AliasModel(pairs).audit()))

    def test_query_exclusion_cannot_hide_mixed_destination(self):
        pairs = self.training(mixed=True)
        model = AliasModel(pairs)
        query = {'source_unit_id': 's2', 'source': {'area_name': 'Dubai Marina'}, 'raw_fields': {'plot_number': 'PARENT001'}}
        d = model.features(query, pairs[0]['target'])
        self.assertFalse(any(a['accepted'] for a in d['learned_aliases']))

    def test_conflicting_parent_destinations_reject(self):
        model = AliasModel(self.training(mixed=True))
        self.assertTrue(all(not a['accepted'] for a in model.audit()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
