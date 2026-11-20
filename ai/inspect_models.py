"""python -m ai.inspect_models
Loads the five checkpoints, prints task and class names and the app category each class maps to.
Unmapped classes can be added to ai/class_map.json (a skeleton is printed at the end)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ai import category_mapper as CM, manager as M

def main():
    cfg = {}
    ov = CM.load_overrides(os.path.join(M.HERE, 'class_map.json'))
    skeleton, problems = {}, 0
    for d in M.get_detectors(cfg):
        d.load()
        print(f'\n== {d.display_name}  ({d._pick_file()})')
        if not d.model:
            problems += 1
            print('   NOT LOADED:', d.error)
            continue
        print(f'   task: {d.task}   classes: {len(d.names)}')
        skeleton[d.name] = {}
        for cid, label in sorted(d.names.items()):
            cat, how = CM.map_label(d.name, label, cid, ov)
            flag = '' if cat else '   <-- UNMAPPED: add it to ai/class_map.json'
            print(f'   {int(cid):>3}  {label:<28} -> {cat or "(unclassified)":<26} [{how}]{flag}')
            if not cat:
                skeleton[d.name][str(label)] = 'Other'
    print('\nSkeleton for unmapped classes (edit the categories, then merge into ai/class_map.json):')
    print(json.dumps({k: v for k, v in skeleton.items() if v}, indent=2))
    print(f'\n{problems} checkpoint(s) could not be loaded.')

if __name__ == '__main__':
    main()
