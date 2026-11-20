# Model report
_Generated 2026-11-14 03:08 by `python -m ai.model_report`._

## 1. Checkpoints

| Slot | File | Task | Classes | Trained from | Epochs | Family | Size | Train-run val (P / R / mAP50) |
|---|---|---|---|---|---|---|---|---|
| civicresolve (Model_1) | `Model_1.pt` | detect | 2 | yolov8n.pt | 10 | pothole_garbage | 6.2 MB | 0.812 / 0.688 / 0.774 |
| civic_guardian (Model_2) | `Model_2.pt` | detect | 7 | best.pt | 10 | civic_guardian | 5.2 MB | 0.742 / 0.5 / 0.548 |
| streetlight (Model_3) | `Model_3.pt` | detect | 4 | yolo26n.pt | 20 | streetlight | 5.1 MB | 0.848 / 0.714 / 0.813 |
| own_model (Model_4) | `Model_4.pt` | detect | 2 | best.pt | 40 | pothole_garbage | 6.2 MB | 0.799 / 0.776 / 0.829 |

_The last column is what the checkpoint recorded at the end of its own training run on that run's own validation split; it is not comparable between rows trained on different datasets._

### Classes and the app category each maps to

* **civicresolve**: pothole → Pothole, garbage → Garbage
* **civic_guardian**: pothole → Pothole, cracks → Road Damage, open_manhole → Open Manhole, fallen_tree → Fallen Tree, garbage → Garbage, streetlight → Streetlight, water_leak → Water Leakage
* **streetlight**: pothole → Pothole, garbage → Garbage, broken_street_light → Streetlight, fallen_tree → Fallen Tree
* **own_model**: pothole → Pothole, garbage → Garbage

### SHA-256 (paste into `AI_MODEL_SHA256` in config.py to pin the exact files)

```
'Model_1.pt': '4b877361a6e89afad1b94fbd456f22a480439dc37373cfed4684e151b6aa42c3',
'Model_2.pt': '11a5db9c6ad7252bcd336d6c7d84630f504683e7429f9e71d6bc7cc8af75ea81',
'Model_3.pt': 'af6bcd8e0959df8823998c1685080d42a17f5f5c710c54935ce62c4c73caf49e',
'Model_4.pt': '1e893e07a0f8429a6cb227ecdd947db73c615c3ce09b3eda93ba7c8a31bee8ef',
```

## 2. Measured on 67 labelled images (Pothole)

### Issues the app would NOT flag as low-score (reliability-weighted score >= 0.45): the operating point

| Strategy | True pos | False pos | Missed | Precision | Recall | F1 | Model time / image |
|---|---|---|---|---|---|---|---|
| civicresolve | 72 | 5 | 82 | 0.935 | 0.468 | 0.623 | 92 ms |
| civic_guardian | 65 | 7 | 89 | 0.903 | 0.422 | 0.575 | 69 ms |
| streetlight | 81 | 12 | 73 | 0.871 | 0.526 | 0.656 | 63 ms |
| own_model | 101 | 8 | 53 | 0.927 | 0.656 | 0.768 | 76 ms |
| all four, independent votes | 120 | 27 | 34 | 0.816 | 0.779 | 0.797 |  |
| all four, families merged (the app) | 119 | 24 | 35 | 0.832 | 0.773 | 0.801 |  |

### Every reported issue, no score cut

| Strategy | True pos | False pos | Missed | Precision | Recall | F1 | Model time / image |
|---|---|---|---|---|---|---|---|
| civicresolve | 98 | 23 | 56 | 0.810 | 0.636 | 0.713 | 92 ms |
| civic_guardian | 91 | 20 | 63 | 0.820 | 0.591 | 0.687 | 69 ms |
| streetlight | 114 | 53 | 40 | 0.683 | 0.740 | 0.710 | 63 ms |
| own_model | 128 | 37 | 26 | 0.776 | 0.831 | 0.803 | 76 ms |
| all four, independent votes | 129 | 75 | 25 | 0.632 | 0.838 | 0.721 |  |
| all four, families merged (the app) | 129 | 75 | 25 | 0.632 | 0.838 | 0.721 |  |

One reported issue = one object; a hit needs IoU >= 0.5 with a labelled box. Only categories present in your labels are scored.
"Independent votes" and "families merged" find the same boxes: merging a family changes the SCORE (it stops two related checkpoints from reinforcing each other), not the box count.
