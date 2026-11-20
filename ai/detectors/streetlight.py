from ai.detectors.base import BaseDetector

class StreetlightDetector(BaseDetector):
    """Model_3: pothole, garbage, broken street light and fallen tree, file ai/models/Model_3.pt (was multiclass_streetlight_tree.pt)."""
    name, display_name = 'streetlight', 'Model_3'
    filenames = ('Model_3.pt', 'streetlight_best.pt', 'multiclass_streetlight_tree.pt')
