"""Extra models beyond Model_1..Model_5, without code changes.
Put the checkpoint in ai/models/ and add one line to AI_EXTRA_MODELS in config.py, e.g.
    AI_EXTRA_MODELS = {'road_v3': {'file': 'road_v3.pt', 'display': 'Model_6'}}
An extra whose file is missing is skipped; once present it is loaded, mapped, used in the decision and listed in the admin panel like the others."""
import os, re
from ai.detectors.base import BaseDetector

DEFAULT_EXTRAS = {}
NAME_OK = re.compile(r'^[a-z][a-z0-9_]{2,31}$')                  # stored in the database (model_name, 40 characters)
BUILTIN = {'civicresolve', 'civic_guardian', 'streetlight', 'own_model', 'best_civic_model'}

def build_extras(cfg, models_dir):
    specs = cfg.get('AI_EXTRA_MODELS', DEFAULT_EXTRAS) or {}
    out = []
    for name, spec in specs.items():
        spec = {'file': spec} if isinstance(spec, str) else dict(spec or {})
        fn = os.path.basename(str(spec.get('file') or ''))
        if not NAME_OK.match(str(name)) or name in BUILTIN or not fn.lower().endswith('.pt'):
            continue                                                  # a bad entry never breaks the other models
        if not os.path.lexists(os.path.join(models_dir, fn)):
            continue
        cls = type('Extra_' + name, (BaseDetector,), {'name': name, 'display_name': str(spec.get('display') or name), 'filenames': (fn,)})
        out.append(cls(models_dir, cfg))
    return out

def extras_signature(cfg, models_dir):
    """Part of the detector cache key: adding / removing the file or the config entry takes effect without restarting the cache logic."""
    return tuple(sorted((n, os.path.lexists(os.path.join(models_dir, os.path.basename(str((s or {}).get('file') if isinstance(s, dict) else s or ''))))) for n, s in (cfg.get('AI_EXTRA_MODELS', DEFAULT_EXTRAS) or {}).items()))
