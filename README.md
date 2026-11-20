# Community Report Care 2.1

Flask + **Flask-SQLAlchemy** + **Flask-Login** + Bootstrap 5 + Chart.js + Leaflet + optional YOLO.
Citizen portal and a separate Admin Portal share one database.

## 1. Run it
```
pip install -r requirements.txt
copy .env.example .env          (Mac/Linux: cp .env.example .env)   then edit SECRET_KEY and ADMIN_PASSWORD
python tests/test_app.py        # everything should say PASS (also: test_ai_pipeline, test_ai_video, test_ai_flask, test_multi_video, test_real_models)
python seed_demo.py             # optional demo data (citizen: demo@crc.local / Demo@12345)
python app.py                   # http://127.0.0.1:5000
```
* Citizens: Register, then Login (email + password) **or** Login with OTP (mobile number; code is shown on screen because no SMS gateway is connected).
* Admins: footer link **Admin Login** (`/admin/login`). The first admin comes from `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`; more admins can only be created by an existing admin (Admin > Settings). Citizens can never register as admin.
* The tests: `test_app` (application), `test_ai_pipeline` / `test_ai_video` / `test_ai_flask` (AI logic with a fake YOLO), `test_multi_video` (one video -> several complaints, location provenance, old-database safety, JS syntax), `test_real_models` (the real checkpoints + 4 real photos; skips itself if ultralytics or the files are missing). `tests/browser_test.py` is an optional Playwright script that drives the wizard in a real browser (GPS allowed / denied / multi-issue video).

## 2. Pages
Citizen: Overview, Report an Issue (AI or manual, camera + gallery, video record/upload, optional description, review screen), My Complaints, Track, Map View, Notifications, Profile (also confirm or dispute a "Resolved" fix; before/after photos).
Admin: Overview, All Complaints (filters + CSV export), complaint detail (status, category, department, officer, priority, after-repair photo, AI verdict, every model's prediction, video evidence), AI Review + accuracy, Map View, Departments, Community Votes, Notifications (alerts), Reports & Analytics, Manage Users, Settings (profile, password, new admin, activity log).

## 3. AI: five YOLO models, images AND video
The five model slots in `ai/models/` (Model_1 to Model_5) and the file each one loads (a slot also accepts its original file name, e.g. `pothole_garbage_v2.pt` or `own_best.pt`; to point a slot at another file use `AI_MODEL_FILES` in `config.py`):
```
slot            file                              what it is (read from the checkpoint itself)
civicresolve    Model_1.pt  (was pothole_garbage_v1.pt)          10 classes (damaged road, pothole, parking, road sign, fallen trees, garbage, vandalism, dead animal, concrete, electric wires), YOLOv8m, 10 epochs
civic_guardian  Model_2.pt  (was civic_guardian.pt)          pothole, cracks, open_manhole, fallen_tree, garbage, streetlight, water_leak
streetlight     Model_3.pt  (was multiclass_streetlight_tree.pt)   pothole, garbage, broken_street_light, fallen_tree
own_model       Model_4.pt  (was pothole_garbage_v2.pt)          pothole + garbage, YOLOv8n, 40 epochs
best_civic_model Model_5.pt (was best_civic_model.pt)          pothole only, YOLO11n, 100 epochs
```
**Model_1 and Model_4 are one family** (`AI_FAMILY_BY_FILE`): checkpoints trained from one another make correlated mistakes, so they count as ONE vote, never as two models "agreeing". `Model_2.pt` also lists `best.pt` as its base model; add it to the family map if you consider it related.
**Adding another model** (for example `Model_5.pt`) and **changing the footer company name**: see `docs/ADD_A_MODEL_AND_FOOTER.md`. A new model needs no code: copy the file into `ai/models/`, run `python -m ai.inspect_models`, fix any UNMAPPED class in `ai/class_map.json`, restart.

**What is measured and what is not**: `docs/MODEL_REPORT.md` (regenerate with `python -m ai.model_report`) holds the facts read from the checkpoints and results on 67 held-out pothole photos. Only potholes could be measured; garbage, streetlight, manhole, tree, crack and water-leak scores are UNMEASURED until you run `ai.calibrate` on labelled photos of them. `docs/AI_FINDINGS.md` explains the numbers.
`pip install ultralytics opencv-python`. Without any checkpoint the app still works: AI reporting says "model not available" and the citizen picks the category. If ONE model is missing or crashes, the others still run and the problem is shown (in the AI step and in the admin panel).

**First run (in this order)**
1. `python -m ai.inspect_models`: loads each checkpoint, prints its task and class names and what each class maps to. Anything marked UNMAPPED goes into `ai/class_map.json` (format shown inside that file). Class names are never assumed to match between models.
2. `python -m ai.calibrate --images val/images --labels val/labels --gt-map gt_map.json`: measures each model's precision per category on your validation photos and writes `ai/reliability.json`. Until then a neutral default is used and results are marked *uncalibrated*.
3. `python -m ai.benchmark --images some_photos/`: times each model, memory use, and sequential vs parallel. Set `AI_PARALLEL = True` in `config.py` only if parallel is clearly faster.
4. `python tests/test_ai_pipeline.py` and `python tests/test_ai_video.py`: logic tests (use a fake YOLO, no weights needed). `python tests/test_app.py`: the application tests.

**How a decision is made** (`ai/decision.py`): raw confidences of different models are NOT comparable, so score = confidence x that model's validation reliability for that category. Boxes that overlap (IoU >= `AI_IOU_MATCH`) are one physical object; separate objects are separate issues, not conflicts. Models that agree reinforce each other; if the best two categories are closer than `AI_CONFLICT_MARGIN`, or the score is below `AI_MIN_SCORE`, the citizen/admin is asked to confirm. Pothole + road-damage on one object is treated as compatible (the specific one wins). The AI only suggests: the complaint's category is always what the citizen chose, and the result is never described as verified.

**One video, several complaints** (Report an Issue > AI report > video): each separate physical issue found in the video is offered with its photo, time and (when available) GPS location. A category seen at two places or two moments is two issues (time gap `VIDEO_ISSUE_GAP_SEC`, GPS distance `VIDEO_SAME_SPOT_M`, or different boxes). The citizen ticks the real ones, confirms each category, places each pin, and submits: **one complaint per ticked issue**, created together or not at all (`POST /report/video/submit`), each with its own frame, AI record, moment and location. All of them keep the same original video as evidence and link to each other (shared `group_id`).

**The AI output video** (`ai/video_render.py`): after the analysis the server also renders the WHOLE video again with every issue boxed and labelled (`#1 Pothole 82%`, the same numbers as in the issue list). The models only look at sampled frames, so a **thick** box marks a moment the AI really checked and a **thin** box follows it for about `VIDEO_TRACK_SEC` seconds (optical-flow tracking; it stops when the object is lost, so no box floats over empty road). It is played in the report wizard (with a ▶ button per issue that jumps to it) and in the video evidence of every complaint made from the video, with a switch between *With AI boxes* and *Original video*; the original upload is never modified. If **ffmpeg** is installed the output is H.264 MP4 and keeps the original audio (plays on every phone); without it a WebM is written (plays in Chrome, Firefox, Edge, Android; very old iPhones may not play WebM; install ffmpeg to be safe). Settings: `VIDEO_ANNOTATED_OUTPUT`, `VIDEO_OUT_MAX_SIDE`, `VIDEO_OUT_MAX_FPS`, `VIDEO_TRACK_SEC`, `VIDEO_USE_FFMPEG`. If rendering fails the analysis still completes.

**Location** (one optional request): Step 1 has a "Use my current location" tick-box. Only ticking it asks the browser, once; the fix is kept in the form draft (sessionStorage) and later steps never ask again unless the citizen presses the GPS button. States: *captured* (green, with accuracy), *not captured yet* (amber), *unavailable* (grey; the citizen picks the spot on the map in Step 5; GPS denial never blocks a report). A video has ONE location by default (asked once, used for all its issues); per-issue pins appear only if the GPS track shows the issues are at different places, or the citizen ticks "These issues are at different places". Step 5 shows the pin, an accuracy circle, latitude, longitude and accuracy, and the pin can be dragged. The server records how the location came about (`complaint_geo`: device GPS / GPS sampled while filming / upload-time fix / pin moved by the citizen / map pin / landmark only, accuracy, distance the pin was moved, seconds between detection and GPS sample). A phone's GPS is where the phone was, never presented as the exact spot of a pothole. A GPS fix taken when a gallery video is uploaded is offered only as *approximate*, because the video may have been filmed elsewhere.

**Video evidence** (Report an Issue > AI report > Record Video / Upload Video): the citizen records in the page (up to 30 s, optional GPS sampled while filming), uses the phone's camera app, or uploads from the gallery. The server checks the real file type, picks the sharpest frame in evenly spaced moments (max `VIDEO_MAX_FRAMES`), runs the same five models on each frame and shows issues with timestamps. The clearest frame becomes the complaint's normal photo, so the rest of the wizard is unchanged. Admins see the player, a clickable detection timeline, annotated frames, every model's prediction and the GPS fixes on the complaint page. Un-submitted videos are deleted after 2 days.

**Security**: a `.pt` file is a Python pickle, so loading one can run code. Only files directly inside `ai/models/` are loaded (no request-supplied paths, no symlinks leaving the folder, size limit, optional SHA-256 pin per file in `AI_MODEL_SHA256`). Only put checkpoints you trained or trust there.

**Database**: five new tables (`ai_predictions`, `ai_analyses`, `complaint_videos`, `complaint_geo`, `complaint_video_issues`) are created automatically by `db.create_all()` at start-up. No existing table or complaint row is altered or deleted; the old `ai_detections` row is still written as the one-line summary, so every old screen and report keeps working. Complaints made before this upgrade simply have no extra rows.

## 4. Images
Drop files into `static/img/` (names in `static/img/README.txt`). Missing images never break a page.

## 5. Security notes
Hashed passwords, CSRF token on every POST, role checks on every admin route (server side), lock-out after 5 failed logins (email+IP) for 15 minutes, deactivated accounts are logged out instantly, uploads validated + re-encoded, citizens see only their own (or supported) complaints, admin actions are written to an audit log.
Before going live: set a strong `SECRET_KEY`, use HTTPS, run behind a real WSGI server (gunicorn/waitress), connect a real SMS gateway for OTP.

## 6. Test on a real phone (camera + GPS need HTTPS or localhost)
Use a free HTTPS host or a tunnel (e.g. ngrok) and open the https link on Android. Check: Take a Photo, Upload Photo, Record Video (live camera needs HTTPS/localhost; on plain http the phone's camera app opens instead), Upload Video, Retake/Replace, deny GPS then tap the map, AI report without a model, manual report without a photo.

## 7. Layout notes (responsive)
* The main content fills all the space next to the sidebar (no fixed max-width, except pages wider than 2200 px and form pages, which stay centred and readable).
* Breakpoints: 1199 px stat cards go 5 -> 3 per row; 900 px dashboard sections stack; 767 px stat cards 2 per row and report cards stack; below 992 px the sidebar becomes a slide-in menu (hamburger button).
* Checked in headless Chromium at 1366x768, 1920x1080, 1180x820, 820x1180 and 390x844: no horizontal scrolling on any page, content uses about 99-100 % of the free width.
* The background photo (`bg-*.jpg`) covers the whole window behind the content, with a light veil so text stays readable. Change the veil in `.page-bg::after` in `style.css`.
