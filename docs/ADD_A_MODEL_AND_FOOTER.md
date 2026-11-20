# Guide 1: Model_5 (`Model_5.pt`) and adding a 6th model

A new model needs **no code**. Do these steps in order.

**1. Copy the file** into the folder `ai/models/`, keeping the exact name `Model_5.pt` (the old name `best_civic_model.pt` is still accepted).
(`best_civic_model` is the built-in **Model_5** slot: no config entry is needed. Until the file is there, AI Review shows Model_5 as "not available" and the other four still run. For a 6th model with another name, add one line to `AI_EXTRA_MODELS`, see "Another name" below.)
Only add files you trained yourself or fully trust: a `.pt` file is a Python pickle and loading it can run code.

**2. Check what it contains.** In the project folder run:

    python -m ai.inspect_models

Find the block `== Model_5 (Model_5.pt)`. It prints every class name inside the model and the app category it maps to.
* Every class says a category (Pothole, Garbage …): nothing more to do for mapping.
* A class says `UNMAPPED` (for example `kachra`): open `ai/class_map.json` and add the model name and the class, e.g.

      {"best_civic_model": {"kachra": "Garbage", "gaddha": "Pothole"}}

  (the key is the model's own class name or its number; the value must be one of the 15 app categories). An unmapped class is never guessed: it stays "unclassified" and cannot create a complaint by itself.

**3. Restart the app** (`python app.py`). Log in as admin, open **AI Review**: the table "Models" now lists "Model_5" with the file loaded (or the reason it did not load). From now on every photo and every video frame also runs through it, and its predictions are stored and shown like the others.

**4. Is it related to another model?** If `Model_5.pt` was trained *from* one of the others (fine-tuned from `own_model`, for instance), they make the same mistakes, so they should count as ONE vote. In `config.py` put both file names in the same family:

      AI_FAMILY_BY_FILE = {'Model_1.pt': 'pothole_garbage', 'Model_4.pt': 'pothole_garbage', 'Model_5.pt': 'pothole_garbage'}

(`python -m ai.model_report` prints a "Trained from" column read from each checkpoint to help you decide.)

**5. Measure it (strongly recommended).** Until you do, its confidence is weighted with a neutral 0.6 and shown as "uncalibrated".
With a folder of labelled validation photos it has NOT been trained on:

      python -m ai.calibrate --images val/images --labels val/labels --gt-map gt_map.json
      python -m ai.model_report --images val/images --labels val/labels --gt-map gt_map.json

(`gt_map.json` says which label number is which category, e.g. `{"0": "Pothole", "1": "Garbage"}`.) This writes `ai/reliability.json` and `docs/MODEL_REPORT.md`.
Only categories present in your labels get numbers. Compare the combined result with and without the new model before you trust it: in our tests four models together were only slightly better than the best single one.

**6. Optional pin.** `python -m ai.model_report` prints the SHA-256 of every file. Paste the line for the new file into `AI_MODEL_SHA256` in `config.py`: a file that does not match is never loaded.

### Another name, or several new models
In `config.py`:

      AI_EXTRA_MODELS = {
          'road_v3': {'file': 'road_v3.pt', 'display': 'Model_6'},
      }

The key (`road_v3`) is the id stored in the database: lowercase letters, digits and `_`, 3-32 characters, not one of the five built-in ids. An entry whose file is not in `ai/models/` is skipped silently. A corrupt file disables only itself.
**Speed:** every model runs on every photo and on every sampled video frame, so each extra model makes analysis slower (check with `python -m ai.benchmark`).

### Replace a built-in model instead of adding a sixth
Copy the new file into `ai/models/` and point the slot at it in `config.py`: `AI_MODEL_FILES = {'own_model': 'my_new_best.pt'}`.

### If it does not appear
* AI Review shows it "not loaded" with a reason: wrong file name, corrupt file, or an SHA-256 pin that does not match.
* It is not in the table at all: the file is not in `ai/models/`, the name is not in `AI_EXTRA_MODELS`, or you did not restart.

# Guide 2: put your company name in the footer

The footer reads: `© 2026 <your company>. All rights reserved.` on the landing page and inside the app.

**Easiest: environment variable** (no code edit). Windows PowerShell, before starting the app:

      $env:COMPANY_NAME = "Your Company Pvt. Ltd."
      python app.py

(Linux / Mac: `export COMPANY_NAME="Your Company Pvt. Ltd."`.) Or put the same two settings as lines `COMPANY_NAME=...` in your `.env` file if you use one.

**Or edit `config.py`**: change the default text in the line `COMPANY_NAME = os.environ.get('COMPANY_NAME') or 'Community Report Care'`.

**Year**: it shows the current year by itself (2026 now, 2027 next January). To fix it, set `COPYRIGHT_YEAR` the same way, e.g. `$env:COPYRIGHT_YEAR = "2026"`.

The name is safe to use with symbols such as `&` or `<`: it is escaped automatically. To change the wording or add a link, edit the one line that starts with `©` in `templates/app_base.html` (footer inside the app) and `templates/landing.html` (landing page).
