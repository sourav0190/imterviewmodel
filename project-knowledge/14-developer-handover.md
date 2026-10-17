# 14 - Developer Handover & Onboarding Guide

Welcome to the AI Proctoring Backend codebase! This guide contains everything a new developer or maintainer needs to know to get productive immediately.

---

### 1. 60-Second Quickstart

```bash
# 1. Clone repository
git clone https://github.com/idarkpearl/AiProtctor.git
cd AiProtctor

# 2. Setup virtual environment with Python 3.10 or 3.11
uv venv .venv --python 3.11
uv pip install -r requirements.txt --python .venv/Scripts/python.exe

# 3. Start the server
.\.venv\Scripts\python.exe main.py

# 4. Open browser for visual confirmation
# Visit: http://localhost:8000/test
```

---

### 2. Architecture Map (Where Things Live)

```
Incoming Request
      │
      ▼
main.py ────────────────────────► Sets up CORS, FastAPI app, and mounts /api/v1
      │
      ▼
api/routes.py ──────────────────► Decodes base64 and coordinates detectors
      │
      ├──► detection/face_landmark_detector.py ──► Gaze, Head Pose, Mouth/Talking
      ├──► detection/person_phone_detector.py  ──► YOLOv8s (Person, Phone, Laptop, Book)
      └──► detection/hand_detector.py          ──► MediaPipe Hands (Count up to 4)
      │
      ▼
services/behavior_analyzer.py ──► Scores malpractices and outputs final report
```

---

### 3. How to Make Common Modifications

#### A. How to Add a New Cheating Object (e.g. Smart Watch / Tablet)
1. Check the 80 COCO dataset class indices (e.g., Tablet is often clustered or trained via custom YOLO weights).
2. Add the class index to `self.target_classes` in [`detection/person_phone_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/person_phone_detector.py#L11).
3. Update the loop in `detect()` to check for the new class ID.
4. In [`services/behavior_analyzer.py`](file:///c:/Users/soura/Desktop/hackshift/services/behavior_analyzer.py), assign a penalty weight and error message.

#### B. How to Adjust Suspicion Penalties
* Open [`services/behavior_analyzer.py`](file:///c:/Users/soura/Desktop/hackshift/services/behavior_analyzer.py).
* Modify the points added to `score` for any condition:
  - Phone: line 27 (`score += 60`)
  - Multiple People: line 22 (`score += 50`)
  - Face Missing: line 17 (`score += 40`)
  - 3+ Hands: line 66 (`score += 40`)

#### C. How to Adjust Gaze Sensitivity
* Open [`detection/face_landmark_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/face_landmark_detector.py).
* Yaw threshold: Lines 50–53 (`0.4` threshold for left/right glance). Decrease to `0.3` for stricter detection, increase to `0.5` for looser tolerance.
* Talking threshold: Line 76 (`jaw_open > 0.08`).

---

### 4. Golden Rules for Developers (Avoid Common Pitfalls)

1. **NEVER reload models per request**: Always keep model instances at module-level in `api/routes.py`. Instantiating YOLO or MediaPipe inside an async route will destroy server throughput.
2. **DO NOT enable `reload=True` in Uvicorn**:
   ```python
   # main.py
   uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
   ```
   MediaPipe's C++ binary extensions fail or cause memory leaks when worker processes reload dynamically.
3. **Ignore dead files**:
   - Do NOT edit or import `detection/face_detector.py` or `detection/gaze_detector.py`. They are deprecated stubs.
4. **Use Python 3.10 or 3.11**:
   - Do not attempt to run this project on Python 3.13 or 3.14 on Windows until stable PyTorch and MediaPipe binary wheels are released.

---

### 5. Running Automated Verification

To verify that the microservice, models, and endpoints are functioning correctly without changing code, run the scratch test suite:
```powershell
.\.venv\Scripts\python.exe -c "import requests; r = requests.get('http://localhost:8000/'); print(r.status_code, r.json())"
```
Or execute the comprehensive test script in the workspace scratch directory.
