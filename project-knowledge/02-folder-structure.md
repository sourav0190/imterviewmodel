# 02 - Project Directory Structure

## 1. Directory Tree Map

```
c:\Users\soura\Desktop\hackshift\
├── .dockerignore                       # Docker build exclusions
├── Dockerfile                          # Containerization build specification
├── FINAL_INTEGRATION_STEPS.md          # Guide for migrating Next.js exam pages to this backend
├── NEXTJS_INTEGRATION.md               # Quick Next.js component embed guide
├── ProctoringPanel.jsx                 # Standalone React/Next.js proctoring panel component
├── README.md                           # Repository documentation and schema overview
├── deployment_instructions.md          # Hosting instructions for Render, Railway, AWS, GCP
├── diagnose_mp.py                      # Diagnostic script to check MediaPipe import health
├── frontend_integration_example.js     # Standalone React-Webcam integration example
├── main.py                             # FastAPI application entry point and server startup
├── requirements.txt                    # Python dependencies specification
├── run.bat                             # Windows CMD startup batch script
├── run.ps1                             # Windows PowerShell startup script
├── test_frontend.html                  # Standalone HTML5/JS dashboard for testing with webcam
│
├── api/
│   ├── __pycache__/                    # Compiled Python bytecode
│   └── routes.py                       # REST API endpoint definitions (/api/v1/analyze)
│
├── detection/
│   ├── __pycache__/                    # Compiled Python bytecode
│   ├── face_detector.py                # [LEGACY / DEAD CODE] Abandoned dummy stub
│   ├── face_landmark_detector.py       # ACTIVE: MediaPipe Face Landmarker & Blendshapes
│   ├── gaze_detector.py                # [LEGACY / DEAD CODE] Abandoned dummy stub
│   ├── hand_detector.py                # ACTIVE: MediaPipe Hand Landmarker (up to 4 hands)
│   └── person_phone_detector.py        # ACTIVE: Ultralytics YOLOv8s object detector
│
├── models/
│   ├── face_landmarker.task            # Binary MediaPipe bundle for 478 face landmarks (3.6 MB)
│   └── hand_landmarker.task            # Binary MediaPipe bundle for hand landmarking (7.5 MB)
│
├── services/
│   ├── __pycache__/                    # Compiled Python bytecode
│   └── behavior_analyzer.py            # ACTIVE: Suspicion scoring & malpractice heuristics
│
├── utils/
│   ├── __pycache__/                    # Compiled Python bytecode
│   └── image_utils.py                  # Base64 to OpenCV BGR encoder/decoder
│
├── yolov8m.pt                          # Unused YOLOv8 medium model weights (49.7 MB)
├── yolov8n.pt                          # Unused YOLOv8 nano model weights (6.2 MB)
└── yolov8s.pt                          # ACTIVE: YOLOv8 small model weights (21.5 MB)
```

## 2. File Categorization & Roles

### A. Core Active Source Code
* [`main.py`](file:///c:/Users/soura/Desktop/hackshift/main.py): Server setup, CORS, route mounting, root and test routes.
* [`api/routes.py`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py): Controller mapping incoming requests to detectors and analyzer.
* [`detection/face_landmark_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/face_landmark_detector.py): Computes face presence, gaze yaw, gaze pitch, and talking detection.
* [`detection/person_phone_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/person_phone_detector.py): Executes YOLOv8s bounding box and classification for target exam objects.
* [`detection/hand_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/hand_detector.py): Identifies visible hands to alert on external assistance (3+ hands).
* [`services/behavior_analyzer.py`](file:///c:/Users/soura/Desktop/hackshift/services/behavior_analyzer.py): Aggregates detector outputs into suspicion scores and generates alerts.
* [`utils/image_utils.py`](file:///c:/Users/soura/Desktop/hackshift/utils/image_utils.py): Converts raw data URLs to NumPy arrays.

### B. Frontend & Client Integration Files
* [`test_frontend.html`](file:///c:/Users/soura/Desktop/hackshift/test_frontend.html): Self-contained diagnostic dashboard featuring mirrored webcam preview, live metrics, and malpractice feed.
* [`ProctoringPanel.jsx`](file:///c:/Users/soura/Desktop/hackshift/ProctoringPanel.jsx): Modular React component with internal state and canvas capture.
* [`frontend_integration_example.js`](file:///c:/Users/soura/Desktop/hackshift/frontend_integration_example.js): Reference React component utilizing `react-webcam`.

### C. Dead / Legacy Files
* [`detection/face_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/face_detector.py): Returns static dummy placeholder. Safe to deprecate or delete.
* [`detection/gaze_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/gaze_detector.py): Returns static dummy placeholder. Safe to deprecate or delete.
* `yolov8n.pt` & `yolov8m.pt`: Alternate YOLO weight variants excluded during Docker build by `.dockerignore`.
