"""The five detectors, in the order the admin panel lists them."""
from ai.detectors.base import BaseDetector, Prediction                  # noqa: F401
from ai.detectors.civicresolve import CivicResolveDetector
from ai.detectors.civic_guardian import CivicGuardianDetector
from ai.detectors.streetlight import StreetlightDetector
from ai.detectors.own_model import OwnModelDetector
from ai.detectors.best_civic_model import BestCivicModelDetector

DETECTOR_CLASSES = (CivicResolveDetector, CivicGuardianDetector, StreetlightDetector, OwnModelDetector, BestCivicModelDetector)
