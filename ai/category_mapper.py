"""Maps a model's own class label to one of the app categories (Config.CATEGORIES).
Lookup order for (model, label):
  1. ai/class_map.json per-model overrides
  2. alias table below (spelling variants of common civic-issue names)
  3. whole-word match inside a longer label (e.g. "broken_street_light_2")
Anything else stays unclassified (None): it is stored and shown but not turned into a real category.
Class names and indexes are not assumed to match across models."""
import json, os, re

CANONICAL = ['Pothole', 'Garbage', 'Road Damage', 'Open Manhole', 'Drainage', 'Waterlogging', 'Water Leakage', 'Streetlight',
             'Broken Sign', 'Illegal Parking', 'Fallen Tree', 'Vandalism', 'Dead Animal', 'Damaged Electrical Wires', 'Other']

ALIASES = {
    'Pothole': ['pothole', 'potholes', 'pot_hole', 'road_pothole'],
    'Garbage': ['garbage', 'litter', 'waste', 'trash', 'rubbish', 'garbage_dump', 'garbage_overflow', 'overflowing_bin', 'garbage_bin', 'dumping', 'solid_waste'],
    'Road Damage': ['cracks', 'crack', 'damaged_concrete', 'damaged_road', 'damaged_roads', 'road_damage', 'broken_road', 'road_crack',
                    'alligator_crack', 'longitudinal_crack', 'transverse_crack', 'damaged_pavement', 'broken_pavement', 'damaged_footpath'],
    'Open Manhole': ['open_manhole', 'manhole', 'open_man_hole', 'missing_manhole_cover', 'manhole_open', 'uncovered_manhole'],
    'Drainage': ['drain', 'drains', 'drainage', 'blocked_drain', 'clogged_drain', 'sewer', 'sewage', 'open_drain', 'broken_drain'],
    'Waterlogging': ['waterlogging', 'water_logging', 'waterlogged', 'flooding', 'flooded_road', 'stagnant_water', 'flood'],
    'Water Leakage': ['water_leak', 'water_leakage', 'leakage', 'pipe_leak', 'pipe_leakage', 'burst_pipe', 'leaking_pipe', 'water_leaking'],
    'Streetlight': ['streetlight', 'street_light', 'streetlights', 'broken_street_light', 'broken_streetlight', 'damaged_street_light',
                    'faulty_street_light', 'faulty_streetlight', 'street_lamp', 'lamp_post', 'light_pole', 'broken_light'],
    'Broken Sign': ['broken_sign', 'damaged_sign', 'broken_signboard', 'damaged_signboard', 'broken_sign_board', 'damaged_sign_board', 'bent_sign', 'fallen_sign'],
    'Illegal Parking': ['illegal_parking', 'wrong_parking', 'no_parking', 'parked_illegally', 'illegally_parked'],
    'Fallen Tree': ['fallen_tree', 'tree_fall', 'tree_fallen', 'uprooted_tree', 'broken_tree', 'tree_on_road', 'fallen_branch'],
    'Vandalism': ['vandalism', 'vandalized', 'vandalised', 'graffiti', 'defaced', 'defacement'],
    'Dead Animal': ['dead_animal', 'animal_carcass', 'carcass', 'dead_dog', 'dead_cow', 'dead_cat', 'roadkill'],
    'Damaged Electrical Wires': ['damaged_wires', 'damaged_wire', 'damaged_electrical_wires', 'damaged_electric_wires', 'broken_wire', 'broken_wires',
                                 'exposed_wire', 'exposed_wires', 'hanging_wire', 'hanging_wires', 'loose_wire', 'loose_wires', 'electric_wire',
                                 'electrical_wire', 'power_line', 'fallen_wire', 'sagging_wire'],
    'Other': ['other', 'others'],
}

def norm(label):
    """'Broken Street-Light 2' -> 'broken_street_light_2'"""
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', str(label or '').strip().lower())).strip('_')

_INDEX = {norm(a): cat for cat, al in ALIASES.items() for a in al}
_INDEX.update({norm(c): c for c in CANONICAL})
_LONGEST_FIRST = sorted(_INDEX, key=len, reverse=True)

def load_overrides(path):
    """{model_name: {label_or_class_id: 'Category'}}  (invalid categories are ignored)."""
    try:
        with open(path, encoding='utf-8') as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    out = {}
    for model, table in (raw or {}).items():
        if model.startswith('_') or not isinstance(table, dict):
            continue
        out[model] = {norm(k) if not str(k).isdigit() else str(k): v for k, v in table.items() if v in CANONICAL}
    return out

def map_label(model, label, class_id=None, overrides=None):
    """-> (category or None, how)   how in 'override' | 'alias' | 'partial' | 'unmapped'"""
    table = (overrides or {}).get(model, {})
    key = norm(label)
    if key in table:
        return table[key], 'override'
    if class_id is not None and str(class_id) in table:
        return table[str(class_id)], 'override'
    if key in _INDEX:
        return _INDEX[key], 'alias'
    bare = re.sub(r'_?\d+$', '', key)                    # "pothole_2" -> "pothole"
    if bare and bare in _INDEX:
        return _INDEX[bare], 'alias'
    padded = f'_{bare or key}_'
    for alias in _LONGEST_FIRST:                          # whole-word match inside a longer label
        if len(alias) >= 5 and f'_{alias}_' in padded:
            return _INDEX[alias], 'partial'
    return None, 'unmapped'

def legacy_category(label):
    """Old single-model behaviour: unknown labels become 'Other'."""
    return map_label('', label)[0] or 'Other'
