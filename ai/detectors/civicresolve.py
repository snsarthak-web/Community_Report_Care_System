from ai.detectors.base import BaseDetector

class CivicResolveDetector(BaseDetector):
    """Model_1: 10-class YOLOv8m (road damage, pothole, parking, signs, trees, garbage...), file ai/models/Model_1.pt (was pothole_garbage_v1.pt)."""
    name, display_name = 'civicresolve', 'Model_1'
    filenames = ('Model_1.pt', 'civicresolve.pt', 'pothole_garbage_v1.pt')
