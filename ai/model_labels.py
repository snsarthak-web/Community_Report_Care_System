"""Names shown to people (admin panel, detections table, annotated photos). Internal ids stay the same (database, class_map.json, reliability.json)."""
MODEL_LABELS = {'civicresolve': 'Model_1', 'civic_guardian': 'Model_2', 'streetlight': 'Model_3', 'own_model': 'Model_4', 'best_civic_model': 'Model_5'}

def label(name):
    """Accepts one id or several joined with '+' (as stored in model_name)."""
    if not name:
        return name
    return '+'.join(MODEL_LABELS.get(n, n) for n in str(name).split('+'))
