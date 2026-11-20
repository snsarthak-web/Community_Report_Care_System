from ai.detectors.base import BaseDetector

class OwnModelDetector(BaseDetector):
    """Model_4: pothole + garbage YOLOv8n, file ai/models/Model_4.pt (was pothole_garbage_v2.pt)."""
    name, display_name = 'own_model', 'Model_4'
    filenames = ('Model_4.pt', 'own_best.pt', 'pothole_garbage_v2.pt', 'best.pt')
