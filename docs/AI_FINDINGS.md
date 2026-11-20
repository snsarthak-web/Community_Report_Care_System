# What was measured, and what it means

Data: 665 public pothole photos with boxes (Chitholian dataset, ODbL, via github.com/Muhammad-aa/Pothole-Detector). Reliability was calibrated on the 133-image
validation split; every number below is from the 67-image TEST split, which calibration never saw. The dataset may overlap with what your own checkpoints were trained on,
so treat the numbers as optimistic. There are no photos WITHOUT potholes in it, so the false-alarm rate on clean roads is unknown. Only potholes could be scored.

## Single models (pothole class, ultralytics validation, mAP50)
`Model_4` (was pothole_garbage_v2) 0.84-0.88  >  `Model_3` (was multiclass_streetlight_tree) ~0.77  >  `Model_1` (was pothole_garbage_v1) ~0.75  >  `Model_2` (was civic_guardian) ~0.72 (validation / test split).

## Does combining the four help? (issues the app does not flag as low-score, test split)
| Strategy | Precision | Recall | F1 |
|---|---|---|---|
| best single model (v2) | 0.93 | 0.66 | 0.77 |
| all four combined (the app) | 0.83 | 0.77 | 0.80 |

Combining raises recall (more potholes found) and lowers precision (more false alarms); the net gain is small. Without the score cut the combined result is WORSE than v2
alone (F1 0.72 vs 0.80) because several models draw slightly different boxes around one pothole. Two fixes are in: (1) a tight box inside a loose box of the SAME category is one object;
(2) checkpoints of one family are one vote. Neither changes pothole F1 much; they stop duplicate issues and inflated confidence. The honest value of four models is COVERAGE of
categories (streetlight, manhole, tree, crack, water leak), which this data cannot measure. Because the citizen confirms every AI suggestion, a recall-oriented setting is reasonable.

## What you should do next
Label 30-50 photos per category you care about, run `python -m ai.calibrate`, then `python -m ai.model_report --images ... --labels ... --gt-map ...`. Until then those categories show as *uncalibrated*.
