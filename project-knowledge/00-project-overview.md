# 00 - Project Overview

## 1. Project Identity & Purpose
* **Project Name**: AI Proctoring Backend Service (`AiProtctor`)
* **Repository**: [https://github.com/idarkpearl/AiProtctor](https://github.com/idarkpearl/AiProtctor)
* **Core Purpose**: A lightweight, real-time computer vision microservice designed to monitor candidate behavior during online examinations and technical assessments without requiring dedicated GPU infrastructure or storing invasive biometric records.
* **Problem Solved**: Online assessments suffer from cheating malpractices, including secondary unauthorized devices (smartphones, tablets), unauthorized human assistance (whispering, proxy candidates, third hands in frame), and off-screen reference material (books, notes on lap). Traditional proctoring solutions either require costly manual human invigilators or heavy client-side browser extensions that cause thermal throttling on low-spec student machines.

## 2. Target Users & Stakeholders
1. **EdTech & Assessment Platforms**: Developers integrating automated proctoring into online quiz, interview, or coding assessment platforms (e.g., Next.js exam portals).
2. **Academic Institutions & Universities**: Remote examination boards administering automated tests at scale.
3. **Enterprise Recruitment Portals**: Automated technical hiring platforms verifying candidate authenticity during coding tests.
4. **Candidates / Students**: Benefit from lightweight client-side execution, instant feedback on accidental framing issues (e.g. face obscured), and privacy protection (no biometric facial recognition stored).

## 3. Key Differentiators
* **Hybrid Server-Side Offloading**: Client browsers only capture and transmit lightweight JPEG frames (base64) every 1–2 seconds. Heavy neural network matrix operations run on the backend.
* **Explainable Malpractice Reporting**: Rather than returning an opaque binary verdict ("cheating" / "not cheating"), the engine outputs discrete, audit-ready diagnostic items (e.g., `"Mobile phone detected in frame"`, `"Suspicious hand count: 3 hands detected"`).
* **Privacy-Preserving Architecture**: Does not perform facial identification (FR) or compare against biometric databases. It strictly inspects geometric landmarks, gaze vectors, and object classes.
* **CPU-Feasible Real-Time Inference**: Employs an optimized ensemble of **Ultralytics YOLOv8s** and **Google MediaPipe Tasks** that runs with sub-50ms latency on standard CPU environments.

## 4. Main User Journeys
1. **Exam Session Initialization**:
   - The candidate opens an assessment page (e.g., Next.js or the standalone `test_frontend.html`).
   - The frontend requests webcam permissions (`navigator.mediaDevices.getUserMedia`).
   - A live mirrored video feed renders in the UI.
2. **Periodic Proctoring Loop**:
   - An interval timer captures the current video frame onto an invisible HTML5 canvas (`640x480` or `320x240`).
   - The frame is encoded as a base64 JPEG and transmitted via `POST /api/v1/analyze` to the microservice.
3. **Inference & Risk Aggregation**:
   - The backend runs face landmark detection, YOLO object detection, and hand landmark tracking.
   - The `BehaviorAnalyzer` aggregates infractions into a dynamic `suspicion_score` (0–100%).
4. **Client-Side Alerting & Incident Logging**:
   - The frontend updates the Live Diagnostics panel (Face presence, Person count, Gaze direction, Talking status).
   - If suspicion exceeds threshold levels (e.g., >60% or >80%), warnings are triggered or the exam platform initiates automatic early submission.

## 5. Development Stage & Status
* **Current Stage**: **Functional MVP / Microservice Core**
* **Production Readiness**:
  - Backend Core: Operational and tested.
  - Model Pipeline: Operational with local pretrained `.task` and `.pt` files.
  - Multi-tenant Session Tracking: Not implemented (stateless single-frame analysis).
  - Time-series Smoothing: Planned / Not implemented.
