# 11 - Setup, Execution & Deployment Guide

This guide covers local development, virtual environment setup, containerization, and cloud deployment.

---

### 1. Prerequisites & Environment Matrix

* **Python Version**: Python **3.10** or **3.11** (Recommended: 3.11).
  * *Important*: Avoid Python 3.13+ or 3.14 on Windows, as precompiled C++ wheels for PyTorch and MediaPipe are currently missing or unstable.
* **Hardware Requirements**:
  * Minimum: 2 CPU cores, 2 GB RAM (Required to hold YOLOv8s and MediaPipe in memory).
  * Recommended: 4 CPU cores, 4 GB RAM.
  * GPU: Optional (CUDA is supported by PyTorch/Ultralytics automatically if available, but not required).
* **Client Requirements**: Webcam supporting standard 640x480 video capture.

---

### 2. Local Setup via `uv` (Fastest & Most Reliable)

#### Step 1: Install `uv` (if not already installed)
* **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "C:\Users\$env:USERNAME\.local\bin;$env:Path"
  ```
* **macOS / Linux**:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  ```

#### Step 2: Create Python 3.11 Virtual Environment
```bash
uv venv .venv --python 3.11
```

#### Step 3: Install Dependencies
```bash
uv pip install -r requirements.txt --python .venv/Scripts/python.exe
# On macOS/Linux:
# uv pip install -r requirements.txt --python .venv/bin/python
```

#### Step 4: Run the Server
* **Option A (Quick Script)**:
  * Windows CMD: Double-click `run.bat`
  * Windows PowerShell: `.\run.ps1`
* **Option B (Direct command)**:
  ```powershell
  .\.venv\Scripts\python.exe main.py
  ```

The server will start at:
* API Root: `http://localhost:8000`
* Interactive Test UI: `http://localhost:8000/test`
* Swagger / OpenAPI Docs: `http://localhost:8000/docs`

---

### 3. Docker Deployment

The repository includes a production-ready [`Dockerfile`](file:///c:/Users/soura/Desktop/hackshift/Dockerfile) based on `python:3.10-slim`.

#### Build Container Image:
```bash
docker build -t ai-proctoring-backend .
```

#### Run Container:
```bash
docker run -d -p 8000:8000 --name proctor-service ai-proctoring-backend
```

#### Docker Optimization Notes:
* The `.dockerignore` excludes `yolov8n.pt` and `yolov8m.pt`, keeping image size lean.
* System dependencies `libgl1` and `libglib2.0-0` are installed to support OpenCV image manipulation.

---

### 4. Cloud Deployment Platforms

#### A. Railway.app (Recommended for One-Click Deploy)
1. Push repository to GitHub.
2. Log in to [Railway.app](https://railway.app), click **New Project** $\to$ **Deploy from GitHub repo**.
3. Railway automatically detects the `Dockerfile` and builds the service.
4. Generates a public HTTPS URL (e.g. `https://proctor-engine.up.railway.app`).

#### B. Render.com
1. Create a **New Web Service** linked to your GitHub repo.
2. Select **Runtime**: `Docker`.
3. Instance Plan: Ensure at least **2GB RAM** (free tier with 512MB will crash with Out-Of-Memory during PyTorch model load).

#### C. Google Cloud Run (Serverless Container)
```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/ai-proctor
gcloud run deploy ai-proctor \
    --image gcr.io/PROJECT_ID/ai-proctor \
    --platform managed \
    --memory 2Gi \
    --cpu 2 \
    --port 8000 \
    --allow-unauthenticated
```

---

### 5. Troubleshooting Common Setup Issues

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| `module 'mediapipe' has no attribute 'solutions'` | MediaPipe 1.x moved from legacy `solutions` to `mediapipe.tasks.python.vision`. | Use `FaceLandmarkDetector` (which uses Tasks), not legacy `face_detector.py`. |
| `OpenCV: (-215:Assertion failed) !buf.empty()` | Corrupted or empty base64 string sent to `decode_base64_image`. | `utils/image_utils.py` handles this safely returning `None`, which responds with `400 Bad Request`. |
| `Browser alert: Camera access required` | Browser blocked webcam permissions or page was accessed via unsecure HTTP from another IP. | Access via `http://localhost:8000/test` or enable HTTPS in production. Chrome blocks webcam on remote HTTP origins. |
| Memory OOM Crash during deployment | Hosting instance has less than 1.5 GB RAM. | Upgrade container memory limit to at least **2 GB**. |
