"""Offline field-preserving evidence, never a transaction selector or owner proof.

Only frozen baseline role-correct exact-full-ID links teach aliases. No price, date, size or party
fields are consumed here. Parent codes remain parents even when a building is known.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'frozen_backend'))
from app.crm.registry_locations import RegistryLocationIndex, _area_key, _place_key
from app.crm.transaction_matching import identifier, generic_building

_geo_path = ROOT / 'frozen_analytics' / 'geography.py'
_spec = importlib.util.spec_from_file_location('offline_alias_geography', _geo_path)
_geo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _geo
_spec.loader.exec_module(_geo)
for _name in ('normalize_location_name', 'tower_identity_tokens', 'structural_tower_key'):
    setattr(_geo, _name, lru_cache(maxsize=100_000)(getattr(_geo, _name)))

LOCATION_FIELDS = ('area_name', 'project_name', 'building_name')
ID_FIELDS = ('unit_number', 'property_number', 'plot_number', 'building_number', 'land_number', 'municipality_number')


def _frame(row):
    return row.get('source', row)


def _originals(row):
    s = _frame(row)
    result = []
    for origin, data in [('raw_fields', row.get('raw_fields')), ('source_address_fields', row.get('source_address_fields')), ('original_identifiers', s.get('original_identifiers')), ('raw_location_fields', s.get('raw_location_fields'))]:
        if isinstance(data, dict):
            result.append((origin, data))
    return result


def fields(row, names):
    """Preserve origin and role; do not flatten codes into location labels."""
    result = []
    for field in names:
        found = False
        declared_original = False
        for origin, data in _originals(row):
            declared_original = declared_original or field in data
            value = data.get(field)
            if value is not None and str(value).strip():
                found = True
                result.append({'origin': origin, 'field': field, 'value': str(value)})
        if not found and not (declared_original and field in ID_FIELDS) and _frame(row).get(field):
            result.append({'origin': 'normalized', 'field': field, 'value': str(_frame(row)[field])})
    return result


def _codes(row):
    return [(v['field'], identifier(v['value'])) for v in fields(row, ID_FIELDS) if re.search(r'\d', v['value']) and identifier(v['value'])]


def _kind(value):
    text = str(value or '').lower()
    if any(x in text for x in ('plot', 'land')):
        return 'plot'
    if any(x in text for x in ('villa', 'townhouse')):
        return 'villa'
    return 'unit' if text else ''


def _role_ok(field, source, target, code):
    sk, tk = _kind(_frame(source).get('property_type')), _kind(target.get('property_type'))
    if field == 'unit_number':
        return True
    if field == 'property_number' and sk == tk == 'unit':
        return True
    if field in ('property_number', 'plot_number', 'land_number', 'municipality_number') and sk == tk == 'plot':
        return True
    return field == 'building_number' and sk == tk == 'villa' and bool(re.search(r'[a-z]', code))


def _target_key(target):
    return tuple(_place_key(target.get(f)) for f in LOCATION_FIELDS) + (identifier(str(target.get('unit_number') or '')),)


class AliasModel:
    def __init__(self, baseline_pairs=(), places=(), min_units=3):
        self.places = list(places)
        self.catalog = RegistryLocationIndex(self.places)
        self.min_units = max(3, min_units)
        self.groups = defaultdict(list)
        self.parent_children = defaultdict(set)
        self._target_cache = {}
        self._stats_cache = {}
        self.training_rows = 0
        self.rejected_training_rows = 0
        # Area/legal-district equivalences are conditioned on named DXBI places.
        self.area_bridges = defaultdict(set)
        for p in self.places:
            for name in (p.get('building_label'), p.get('project_label'), p.get('building_key')):
                if name:
                    self.area_bridges[_place_key(name)].add((_area_key(p.get('area_key')), _area_key(p.get('area_label'))))
        self.fit(baseline_pairs)

    def _area_ok(self, source_area, target):
        a = _area_key(source_area)
        b = _area_key(target.get('area_name'))
        if not a or not b:
            return True
        if a == b or _geo.normalize_location_name(source_area) == _geo.normalize_location_name(str(target.get('area_name') or '')):
            return True
        for field in ('building_name', 'project_name', 'building_key'):
            for legal, community in self.area_bridges.get(_place_key(target.get(field)), ()):
                if a in (legal, community) and b in (legal, community):
                    return True
        return False

    def _scope(self, source, target=None):
        area = str(_frame(source).get('area_name') or '')
        # Canonicalize only when DXBI proves a legal-area/community pair.
        for name in ('building_name', 'project_name', 'building_key'):
            if target:
                for legal, community in self.area_bridges.get(_place_key(target.get(name)), ()):
                    if _area_key(area) in (legal, community):
                        return community
        if _area_key(area):
            return _area_key(area)
        for field in ('project_name', 'building_name'):
            value = str(_frame(source).get(field) or '')
            if value and not generic_building(value) and re.search(r'[A-Za-z]', value):
                return field + '::' + _geo.normalize_location_name(value)
        return ''

    def fit(self, baseline_pairs):
        validated = []
        source_targets = defaultdict(set)
        for pair in baseline_pairs:
            source, target = pair['source'], pair['target']
            if 'raw_fields' in pair and 'source' not in source:
                source = {'source': source, 'raw_fields': pair['raw_fields'], 'source_unit_id': pair.get('source_unit_id')}
            source_id = source.get('source_unit_id') or _frame(source).get('source_unit_id')
            codes = _codes(source)
            explicit_units = {code for field, code in codes if field == 'unit_number'}
            target_unit = identifier(str(target.get('unit_number') or ''))
            # Original fields can anchor only their actual child role. Blank
            # UnitNo does not erase a full villa BuildingNo or plot identifier;
            # derived suffixes cannot bootstrap their own aliases.
            original_matches = [(v['field'], identifier(v['value'])) for v in fields(source, ID_FIELDS) if v['origin'] != 'normalized' and identifier(v['value']) == target_unit and _role_ok(v['field'], source, target, identifier(v['value']))]
            if _frame(source).get('event_family') not in (None, '', 'sale') or not source_id or not target_unit or (explicit_units and explicit_units != {target_unit}) or not original_matches or not self._area_ok(_frame(source).get('area_name'), target):
                self.rejected_training_rows += 1
                continue
            validated.append((source, target, source_id, codes, target_unit))
            source_targets[str(source_id)].add(_target_key(target))
        for source, target, source_id, codes, target_unit in validated:
            if len(source_targets[str(source_id)]) != 1:
                self.rejected_training_rows += 1
                continue
            self.training_rows += 1
            destination = _target_key(target)[:3]
            record = (str(source_id), _target_key(target), destination)
            scope = self._scope(source, target)
            if not scope:
                continue
            for field, code in codes:
                if not scope.startswith('building_name::') and field in ('plot_number', 'property_number', 'land_number', 'municipality_number') and code != target_unit:
                    self.groups[('parent', scope, field, code)].append(record)
                    self.parent_children[(scope, field, code)].add(_target_key(target))
            for v in fields(source, ('building_name',)):
                name = _geo.normalize_location_name(v['value'])
                source_markers = _geo.tower_identity_tokens(v['value'])
                target_markers = _geo.tower_identity_tokens(str(target.get('building_name') or ''))
                if name and source_markers == target_markers:
                    self.groups[('building', scope, 'building_name', name)].append(record)
        self._stats_cache.clear()
        return self

    def _alias(self, key, source, target):
        if key not in self._stats_cache:
            records = set(self.groups.get(key, ()))
            by_source, by_target, by_destination = defaultdict(set), defaultdict(set), defaultdict(set)
            for record in records:
                by_source[record[0]].add(record)
                by_target[record[1]].add(record)
                by_destination[record[2]].add(record)
            self._stats_cache[key] = (records, by_source, by_target, by_destination)
        records, by_source, by_target, by_destination = self._stats_cache[key]
        uid = str(source.get('source_unit_id') or _frame(source).get('source_unit_id') or '')
        target_key = _target_key(target)
        # Exclusion touches only records of this source unit and registry unit.
        removed = by_source.get(uid, set()) | by_target.get(target_key, set())
        touched_source = {s for s, _, _ in removed}
        touched_target = {t for _, t, _ in removed}
        source_count = len(by_source) - sum(by_source[s] <= removed for s in touched_source)
        registry_count = len(by_target) - sum(by_target[t] <= removed for t in touched_target)
        destinations = {d for d, values in by_destination.items() if not values <= removed}
        all_units = by_target
        globally_pure = set(by_destination) == {target_key[:3]}
        accepted = bool(key[1]) and globally_pure and len(all_units) >= self.min_units and registry_count >= self.min_units - 1 and source_count >= self.min_units - 1 and destinations == {target_key[:3]}
        return {'kind': key[0], 'source_field': key[2], 'source_key': key[3], 'scope': key[1], 'accepted': accepted, 'independent_source_units': source_count, 'independent_registry_units': registry_count, 'total_registry_units': len(all_units), 'distinct_destinations': len(destinations), 'purity': 1.0 if len(destinations) == 1 else None, 'query_unit_excluded': True, 'baseline_only': True, 'destination': list(target_key[:3])}

    def features(self, source, target):
        s = _frame(source)
        cache_key = tuple(str(target.get(f) or '') for f in (*LOCATION_FIELDS, 'building_key', 'area_key', 'unit_number', 'property_type', 'location_name'))
        if cache_key not in self._target_cache:
            self._target_cache[cache_key] = self.catalog.normalize(target)
        target = self._target_cache[cache_key]
        location = {'strength': 'none', 'rules': [], 'conflicts': [], 'fields': fields(source, LOCATION_FIELDS)}
        ids = {'strength': 'none', 'rules': [], 'conflicts': [], 'scope': 'none', 'fields': fields(source, ID_FIELDS)}
        learned = []
        scope = self._scope(source, target)
        area = s.get('area_name')
        if area and target.get('area_name'):
            if self._area_ok(area, target):
                location['strength'] = 'context'
                location['rules'].append('dxbi_catalog_scoped_area_or_exact_community')
            else:
                location['conflicts'].append('area_or_community_conflict')
        tb = str(target.get('building_name') or '')
        tp = str(target.get('project_name') or '')
        ta = str(target.get('area_name') or '')
        if tb and area and _place_key(tb) == _place_key(area) and not location['conflicts']:
            location['strength'] = 'parent'
            location['rules'].append('exact_community_parent_not_building')
        for f in ('building_name', 'project_name'):
            value = str(s.get(f) or '')
            if not value:
                continue
            key = _geo.normalize_location_name(value)
            equal_building = key and key == _geo.normalize_location_name(tb)
            structural_equal = tb and _geo.structural_tower_key(value) == _geo.structural_tower_key(tb) and _geo.tower_identity_tokens(value) == _geo.tower_identity_tokens(tb)
            equal_building = equal_building or structural_equal
            if equal_building:
                broad = key in {_geo.normalize_location_name(ta), _geo.normalize_location_name(str(s.get('area_name') or ''))}
                location['strength'] = 'parent' if broad else 'building'
                location['rules'].append(f'{f}_exact_target_building' + ('_community_parent' if broad else ''))
            elif key and key == _geo.normalize_location_name(tp):
                if location['strength'] != 'building':
                    location['strength'] = 'parent'
                location['rules'].append(f'{f}_exact_target_project')
            elif f == 'building_name' and tb and _geo.tower_identity_tokens(value) and _geo.tower_identity_tokens(tb) and _geo.tower_identity_tokens(value) != _geo.tower_identity_tokens(tb):
                location['conflicts'].append('numbered_building_identity_conflict')
            if f == 'building_name':
                audit = self._alias(('building', scope, f, key), source, target)
                if audit['total_registry_units']:
                    learned.append(audit)
                if audit['accepted'] and not location['conflicts']:
                    location['strength'] = 'building'
                    location['rules'].append('baseline_independent_building_alias')
                elif key and tb and key not in {_geo.normalize_location_name(v) for v in (tb, tp, ta, str(s.get('area_name') or ''))} and not structural_equal:
                    location['conflicts'].append('explicit_building_label_conflict')
            elif tp and key not in {_geo.normalize_location_name(v) for v in (tb, tp, ta, str(s.get('area_name') or ''))}:
                location['conflicts'].append('explicit_project_or_subcommunity_conflict')
        target_unit = identifier(str(target.get('unit_number') or ''))
        codes = _codes(source)
        units = {code for field, code in codes if field == 'unit_number'}
        full_codes = {code for _, code in codes if re.search(r'[a-z]', code)}
        for field, code in codes:
            parent = len(self.parent_children.get((scope, field, code), ())) > 1
            if parent:
                audit = self._alias(('parent', scope, field, code), source, target)
                learned.append(audit)
                ids['rules'].append('shared_parent_never_child')
                if audit['accepted']:
                    location['strength'] = 'building' if location['strength'] != 'building' else location['strength']
                    location['rules'].append('baseline_independent_parent_plot_to_building')
                    if ids['strength'] == 'none':
                        ids['strength'], ids['scope'] = 'parent', 'parent'
                continue
            if code == target_unit:
                role_ok = _role_ok(field, source, target, code)
                if not role_ok:
                    ids['rules'].append(f'{field}_role_unproven_not_child')
                    continue
                ids['strength'] = 'full' if re.search(r'[a-z]', code) else 'unit'
                ids['scope'] = 'child'
                ids['rules'].append(f'exact_original_{field}_full_identity')
                if field == 'property_number' and _kind(s.get('property_type')) == 'plot' and _kind(target.get('property_type')) == 'plot':
                    ids['rules'].append('property_number_plot_full_code_role_reinterpretation')
            elif field == 'unit_number':
                ids['conflicts'].append('explicit_unit_identity_conflict')
        # Multiple original full unit namespaces never become suffix agreements.
        if len(units) > 1:
            ids['conflicts'].append('conflicting_original_full_unit_ids')
        if target_unit and any(code != target_unit for code in full_codes) and ids['scope'] == 'child':
            # Established parent evidence is exempt: it addresses another grain.
            independent = [(f, code) for f, code in codes if re.search(r'[a-z]', code) and code != target_unit and len(self.parent_children.get((scope, f, code), ())) <= 1]
            if independent:
                ids['conflicts'].append('conflicting_original_full_ids')
        if ids['strength'] == 'none' and target_unit:
            target_suffix = re.search(r'([0-9]+[a-z]?)$', target_unit)
            if target_suffix and any(re.search(r'([0-9]+[a-z]?)$', code) and re.search(r'([0-9]+[a-z]?)$', code).group(1) == target_suffix.group(1) for _, code in codes):
                ids['rules'].append('suffix_similarity_only_not_identity')
        location['conflicts'] = sorted(set(location['conflicts']))
        ids['conflicts'] = sorted(set(ids['conflicts']))
        return {'location': location, 'identifier': ids, 'learned_aliases': learned}

    def qualify(self, source, target):
        detail = self.features(source, target)
        loc, ids = detail['location'], detail['identifier']
        conflict = bool(loc['conflicts'] or ids['conflicts'])
        qualified = not conflict and loc['strength'] in ('building', 'parent') and ids['strength'] in ('full', 'unit') and ids['scope'] == 'child'
        return {'qualified': qualified, 'tier': f"{ids['strength']}_{loc['strength']}", 'evidence': loc['rules'] + ids['rules'], 'conflict': conflict, **detail}

    def audit(self):
        result = []
        for key, records in sorted(self.groups.items()):
            distinct = {(s, t, d) for s, t, d in records}
            units = {t for _, t, _ in distinct}
            destinations = {d for _, _, d in distinct}
            # Every supporting registry unit is held out in turn. No inferred
            # outcome ever enters this immutable training population.
            heldout = True
            for held in units:
                excluded_sources = {s for s, t, _ in distinct if t == held}
                retained = {(s, t, d) for s, t, d in distinct if t != held and s not in excluded_sources}
                heldout = heldout and len({t for _, t, _ in retained}) >= self.min_units - 1 and len({s for s, _, _ in retained}) >= self.min_units - 1 and {d for _, _, d in retained} == destinations and len(destinations) == 1
            result.append({'kind': key[0], 'scope': key[1], 'source_field': key[2], 'source_key': key[3], 'distinct_source_units': len({s for s, _, _ in distinct}), 'distinct_registry_units': len(units), 'distinct_destinations': len(destinations), 'heldout_unit_support': heldout, 'accepted': bool(key[1]) and len(units) >= self.min_units and heldout, 'baseline_only': True})
        return result
