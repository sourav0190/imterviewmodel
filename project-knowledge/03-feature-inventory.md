# 03 - Feature Inventory

This document details all features present in the codebase, their implementation status, business logic, and source code evidence.

---

### Feature 1: Face Presence & Candidate Absence Detection
* **User Problem**: Detects if a candidate steps away from the camera, hides their face, or covers the webcam during an active assessment.
* **Frontend Component**: [`test_frontend.html:L299`](file:///c:/Users/soura/Desktop/hackshift/test_frontend.html#L299) (Displays `DETECT` in green or `NONE` in red).
* **Backend Endpoint**: `POST /api/v1/analyze` in [`api/routes.py:L27`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py#L27).
* **Detector Used**: `FaceLandmarkDetector` via `models/face_landmarker.task`.
* **Business Logic**:
  - If `results.face_landmarks` has 0 faces: `face_present = False`.
  - In `BehaviorAnalyzer`: adds **+40 penalty points** to the suspicion index.
  - Generates alert: `"Face not detected (Candidate might have left or camera obscured)"`.
* **Implementation Status**: **Fully Implemented**.

---

### Feature 2: Multiple Person / Proxy Detection
* **User Problem**: Prevents unauthorized secondary people (friends, tutors, or impostors) from sitting beside the candidate or coaching them.
* **Frontend Component**: [`test_frontend.html:L302`](file:///c:/Users/soura/Desktop/hackshift/test_frontend.html#L302) (Displays person count; turns red if count > 1).
* **Backend Endpoint**: `POST /api/v1/analyze` in [`api/routes.py:L28`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py#L28).
* **Detector Used**: `PersonPhoneDetector` via `yolov8s.pt` (Class `0`).
* **Business Logic**:
  - YOLO counts instances of Class `0` (`person`).
  - If `person_count > 1`: flags `multiple_people = True`.
  - In `BehaviorAnalyzer`: adds **+50 penalty points**.
  - Generates alert: `"Multiple people detected ({count} persons)"`.
* **Implementation Status**: **Fully Implemented**.

---

### Feature 3: Unauthorized Device Detection (Phone & Laptop)
* **User Problem**: Detects candidates holding up smartphones, tablets, or placing a secondary laptop within camera view to look up answers.
* **Frontend Component**: Warning alert feed in [`test_frontend.html:L322`](file:///c:/Users/soura/Desktop/hackshift/test_frontend.html#L322).
* **Backend Endpoint**: `POST /api/v1/analyze` in [`api/routes.py:L28`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py#L28).
* **Detector Used**: `PersonPhoneDetector` via `yolov8s.pt` (Classes `67` [phone] and `63` [laptop]).
* **Business Logic**:
  - Confidence threshold set at `0.20` for sensitivity on partially occluded devices.
  - If cell phone detected: adds **+60 penalty points** and flags `"Mobile phone detected in frame"`.
  - If laptop detected: adds **+30 penalty points** and flags `"Secondary screen/laptop detected"`.
* **Implementation Status**: **Fully Implemented**.

---

### Feature 4: Physical Study Material Detection (Books / Notes)
* **User Problem**: Flags textbooks, open notebooks, or printed cheat sheets brought into camera view.
* **Backend Endpoint**: `POST /api/v1/analyze` in [`api/routes.py:L28`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py#L28).
* **Detector Used**: `PersonPhoneDetector` via `yolov8s.pt` (Class `73` [book]).
* **Business Logic**:
  - If book detected: adds **+45 penalty points**.
  - Generates alert: `"Notebook/Book/Cheat-sheet detected"`.
* **Implementation Status**: **Fully Implemented**.

---

### Feature 5: Gaze Tracking & Suspicious Head Pose (Looking Away / Down)
* **User Problem**: Detects if candidate is constantly looking off-screen to read secondary monitors, notes on walls, or cheat sheets placed on their lap.
* **Frontend Component**: [`test_frontend.html:L305`](file:///c:/Users/soura/Desktop/hackshift/test_frontend.html#L305) (Displays direction: Center, Left, Right, Up, Down).
* **Backend Endpoint**: `POST /api/v1/analyze` in [`api/routes.py:L27`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py#L27).
* **Detector Used**: `FaceLandmarkDetector` extracting MediaPipe blendshapes (`eyeLookOut`, `eyeLookIn`, `eyeLookDown`, `eyeLookUp`).
* **Business Logic**:
  - **Yaw (Left/Right)**: If `eyeLookOutLeft > 0.4` or `eyeLookInRight > 0.4` $\to$ Gaze = "Left" / "Right". Adds **+20 points**, alerts `"Looking away from screen (Direction: {dir})"`.
  - **Contextual Pitch (Down)**:
    - Pitch score calculated as: `(down_left + down_right)/2 - (up_left + up_right)/2`.
    - If `pitch > 0.65`: Severe lap tilt $\to$ Adds **+30 points**, alerts `"Suspiciously looking down (Potential hidden notes)"`.
    - If `0.40 < pitch <= 0.65`: Mild look-down (typing on keyboard) $\to$ Adds **+5 points** without raising an alert banner.
* **Implementation Status**: **Fully Implemented**.

---

### Feature 6: Talking & Mouth Movement Detection
* **User Problem**: Detects whispering, verbal dictation, or candidate reading questions aloud to an external helper or microphone.
* **Frontend Component**: [`test_frontend.html:L308`](file:///c:/Users/soura/Desktop/hackshift/test_frontend.html#L308) (Displays `YES` / `NO`).
* **Backend Endpoint**: `POST /api/v1/analyze` in [`api/routes.py:L27`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py#L27).
* **Detector Used**: `FaceLandmarkDetector` extracting the `jawOpen` blendshape coefficient.
* **Business Logic**:
  - If `jawOpen > 0.08`: flags `is_talking = True`.
  - In `BehaviorAnalyzer`: adds **+15 penalty points**.
  - Generates alert: `"Mouth movement detected (Talking/Whispering)"`.
* **Implementation Status**: **Fully Implemented**.

---

### Feature 7: Multi-Hand Tracking (Third Hand Assistance Alert)
* **User Problem**: Detects external people reaching into the camera frame to type, point at the screen, or hand notes/devices to the candidate.
* **Backend Endpoint**: `POST /api/v1/analyze` in [`api/routes.py:L29`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py#L29).
* **Detector Used**: `HandDetector` using `models/hand_landmarker.task` configured with `num_hands=4` and confidence `0.3`.
* **Business Logic**:
  - Counts detected hands.
  - If `hand_count > 2`: flags external physical assistance.
  - Adds **+40 penalty points**.
  - Generates alert: `"Suspicious hand count: {count} hands detected (Possible assistance)"`.
* **Implementation Status**: **Fully Implemented**.

---

### Feature 8: Composite Suspicion Index (Risk Engine)
* **User Problem**: Translates disparate vision metrics into an intuitive, normalized 0–100% risk index for test administrators.
* **Backend Component**: [`services/behavior_analyzer.py:L8-L70`](file:///c:/Users/soura/Desktop/hackshift/services/behavior_analyzer.py#L8-L70).
* **Business Logic**:
  - Aggregates all active infractions.
  - Enforces upper ceiling: `final_score = min(score, 100)`.
  - Frontend visual representation:
    - 0–30%: Normal (Green)
    - 31–60%: Moderate Warning (Orange)
    - 61–100%: Critical Suspicion (Red)
* **Implementation Status**: **Fully Implemented**.
