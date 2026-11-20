from ai.detectors.base import BaseDetector

class BestCivicModelDetector(BaseDetector):
    """Model_5: pothole-only YOLO11n, file ai/models/Model_5.pt (older names still load)."""
    name, display_name = 'best_civic_model', 'Model_5'
    filenames = ('Model_5.pt', 'best_civic_model.pt', 'model_5.pt')
