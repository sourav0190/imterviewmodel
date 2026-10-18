# AI Proctoring Backend Service

An intelligent, real-time microservice for online exam proctoring. It detects suspicious activities using computer vision and behavioral analysis.

## 🚀 Features

- **Gaze Detection**: Monitors eye movement and head pose to detect if the candidate is looking at notes or secondary screens.
- **Multiple Person Detection**: Detects if more than one person is in the frame.
- **Device Detection**: Identifies unauthorized cell phones, tablets, or laptops.
- **Hand Monitoring**: Tracks up to 4 hands to detect external assistance (3+ hands alert).
- **Notebook/Note Detection**: Flags books or cheat sheets displayed to the camera.
- **Talking Detection**: Real-time mouth movement analysis to detect whispering or verbal assistance.
- **Suspicion Index**: A weighted scoring system that aggregates all alerts into a single risk score (0-100%).

## 🛠 Tech Stack

- **FastAPI**: High-performance Python API framework.
- **YOLOv8 (Ultralytics)**: Advanced object detection for devices and people.
- **MediaPipe Tasks**: Modern landmark API for high-precision face and hand tracking.
- **OpenCV**: Image processing and frame decoding.

## 🏗 Setup & Installation

### 1. Prerequisites
- Python 3.9+
- Webcam for testing

### 2. Clone and Install Dependencies
```bash
git clone <your-repo-url>
cd ai_proctoring_service
pip install -r requirements.txt
```

### 3. Model Downloads
The system requires MediaPipe Task files in the `models/` directory:
- `models/face_landmarker.task`
- `models/hand_landmarker.task`

### 4. Run the Server
```bash
python main.py
```
The server will start at `http://localhost:8000`.

---

## 🔗 Next.js Integration Guide

To integrate this service into your Next.js application, follow these steps:

### 1. Setup Camera Capture
Create a component that captures the webcam frame every 1-2 seconds.

```javascript
// components/ProctoringClient.js
import React, { useRef, useEffect } from 'react';

export default function ProctoringClient() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  useEffect(() => {
    // 1. Initialize Webcam
    navigator.mediaDevices.getUserMedia({ video: true }).then(stream => {
      videoRef.current.srcObject = stream;
    });

    // 2. Poll the Backend
    const interval = setInterval(async () => {
      const canvas = canvasRef.current;
      const context = canvas.getContext('2d');
      context.drawImage(videoRef.current, 0, 0, 640, 480);
      
      const base64Image = canvas.toDataURL('image/jpeg', 0.8);
      
      const response = await fetch('http://localhost:8000/api/v1/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: base64Image })
      });
      
      const result = await response.json();
      console.log('Proctoring Report:', result);
      
      // Handle alerts (e.g., set state to show warnings)
      if (result.suspicion_score > 70) {
        alert("Warning: Suspicious activity detected!");
      }
    }, 2000); // Send every 2 seconds

    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <video ref={videoRef} autoPlay style={{ width: '400px' }} />
      <canvas ref={canvasRef} style={{ display: 'none' }} width="640" height="480" />
    </div>
  );
}
```

### 2. API Schema
**Endpoint**: `POST /api/v1/analyze`  
**Request**:
```json
{
  "image": "data:image/jpeg;base64,..."
}
```
**Response**:
```json
{
  "face_present": true,
  "multiple_people": false,
  "person_count": 1,
  "phone_detected": false,
  "looking_away": false,
  "gaze_direction": "Center",
  "is_talking": false,
  "suspicion_score": 5,
  "malpractices": []
}
```

## 📜 Malpractice List Explained

| Alert | Trigger Condition |
|-------|-------------------|
| "Face not detected" | No face found in the camera view. |
| "Multiple people detected" | More than 1 person found (e.g., proxy candidate). |
| "Looking away from screen" | Eye/Head orientation strongly shifted left/right/up. |
| "Suspiciously looking down" | Head tilted deeply down (e.g., looking at a phone in lap). |
| "Mouth movement detected" | Excessive jaw movement (talking or whispering). |
| "Suspicious hand count" | 3 or more hands detected (assistance from others). |

## 🚢 Deployment

Since this is a standalone microservice, you can deploy it independently using Docker or direct Python hosting.

### 1. Using Docker (Recommended)
Build and run the container:
```bash
docker build -t ai-proctor-backend .
docker run -p 8000:8000 ai-proctor-backend
```

### 2. Deployment Platforms
- **Render / Railway**: Recommended for easy Python/Docker deployment.
- **AWS / GCP / Azure**: Use **AWS App Runner** or **Google Cloud Run** for high scalability.

> [!NOTE]
> Ensure your deployment environment has at least 2GB of RAM for YOLOv8 model loading.

---

## 🗄️ Interview Intelligence Agent - PostgreSQL Persistence & Migrations

The Interview Intelligence Agent supports robust database-backed persistence using **SQLAlchemy 2.0** and **Alembic** migrations. All interview sessions, transcript segments, structured notes, rubric-based answer evaluations, and final executive reports are persisted transactionally to PostgreSQL.

### 1. Configuration

Set the environment variables in your `.env` file (see `.env.example`):

```bash
# Persistence mode: 'postgres' (required in production) or 'memory' (unit tests/offline dev)
INTERVIEW_PERSISTENCE_BACKEND=postgres

# PostgreSQL Connection String (supports psycopg3 or standard postgresql dialect)
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/aiproctor
```

> [!IMPORTANT]
> When `APP_ENV=production`, `validate_production_security()` strictly enforces that `INTERVIEW_PERSISTENCE_BACKEND=postgres` and `DATABASE_URL` is set to an active PostgreSQL database. In-memory storage is disallowed in production to prevent silent data loss upon worker restarts.

### 2. Alembic Migrations

Run database migrations to initialize or update schema:

```bash
# Apply all pending migrations to the latest revision
alembic upgrade head

# Roll back the latest migration
alembic downgrade -1

# View migration history
alembic history
```

### 3. Local Development Database Setup

1. **Start PostgreSQL**:
   Ensure PostgreSQL is running locally on port 5432:
   ```powershell
   Get-Service postgresql* | Start-Service
   ```

2. **Create the Database**:
   ```sql
   CREATE DATABASE aiproctor;
   ```

3. **Install Dependencies**:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. **Apply Migrations**:
   ```powershell
   .\.venv\Scripts\alembic.exe upgrade head
   ```

5. **Start Application**:
   ```powershell
   .\.venv\Scripts\uvicorn.exe main:app --reload --port 8000
   ```

### 4. Database Reset (Development Only)

> [!CAUTION]
> **WARNING: Resetting the database permanently destroys all stored sessions, transcripts, evaluations, and reports.** Never execute this against staging or production environments.

To reset the database during local development:
```powershell
# Roll back all migrations to base:
.\.venv\Scripts\alembic.exe downgrade base

# Re-apply all migrations:
.\.venv\Scripts\alembic.exe upgrade head
```

Or via psql:
```sql
DROP DATABASE aiproctor;
CREATE DATABASE aiproctor;
```
followed by `alembic upgrade head`.

### 5. Multi-Worker & Distributed Architectures

- **State Persistence**: PostgreSQL guarantees that all session state, transcript segments, answer evaluations, and finalized reports survive container and worker restarts.
- **WebSocket Event Broadcasting**: PostgreSQL alone handles persistent state storage; in a multi-worker application deployment (e.g., Gunicorn with multiple Uvicorn workers or multiple Kubernetes pods), WebSocket connections are terminated per worker. Multi-worker live broadcasting requires a distributed event backplane (such as **Redis Pub/Sub**) to fan out transcript and evaluation events across worker processes.

---

## 🎥 Jitsi Meet Integration & Automated Interview Notes

AiProtctor integrates **Jitsi Meet** as its official video meeting platform, connecting multi-participant video interviews to the automated Interview Intelligence Agent.

### 1. Architecture & Design Decisions

```
+-----------------------------------------------------------------------------------+
|                              AiProtctor Dashboard                                 |
|                                                                                   |
|  +-------------------------------------+   +-----------------------------------+  |
|  |     Embedded Jitsi Meet IFrame      |   |        Live Interview Feed        |  |
|  |   (Official IFrame API: meet.jit.si)|   |                                   |  |
|  |   - High-entropy room tokens        |   |   🎙️ Real-Time Transcript Stream  |  |
|  |   - Full video & audio controls     |   |   📝 Structured QA Notes          |  |
|  |   - Participant join/leave events   |   |   ⚖️ Dimensional Rubric Scoring   |  |
|  +-------------------------------------+   +-----------------------------------+  |
+-----------------------------------------------------------------------------------+
                                  │                                   ▲
                                  │ (Room creation & Webhooks)        │ (WebSocket Stream)
                                  ▼                                   │
+-----------------------------------------------------------------------------------+
|                         FastAPI Backend (AiProtctor)                              |
|                                                                                   |
|  +-----------------------------+       +---------------------------------------+  |
|  |  Jitsi Integration Package  | ----> |      Interview Session Pipeline       |  |
|  |  (interview_agent/          |       |      - Question Detector              |  |
|  |   integrations/jitsi/)      |       |      - Notes Service (Factual notes)  |  |
|  |  - Room Manager (Entropy)   |       |      - Answer Evaluator (Rubric)      |  |
|  |  - Transcription Adapter    |       |      - Report Service                 |  |
|  |  - HMAC Signature Check     |       +---------------------------------------+  |
|  +-----------------------------+                            │                     |
+-------------------------------------------------------------│---------------------+
                                                              ▼
                                             +----------------------------------+
                                             |      PostgreSQL Persistence      |
                                             |  - Sessions & Jitsi Room Config  |
                                             |  - Transcript Segments           |
                                             |  - Structured Notes & Reports    |
                                             +----------------------------------+
```

### 2. Supported Deployments: Public meet.jit.si vs Self-Hosted vs 8x8 JaaS

| Feature | Public (`meet.jit.si`) | Self-Hosted Jitsi Meet | Jitsi as a Service (JaaS) |
|---|---|---|---|
| **Setup Complexity** | Zero infrastructure; instant dev setup | Requires Linux VM with Docker / Debian | Managed cloud subscription by 8x8 |
| **Room Privacy** | Public server; secured via high-entropy unpredictable room tokens | Fully isolated on private domain & VPC | Private domain (e.g. `8x8.vc`) |
| **Authentication** | Anonymous rooms | JWT tokens (`JITSI_SECRET` / RS256/HS256) | Signed JaaS JWTs (`JITSI_APP_ID`) |
| **Server-Side Audio Taps** | Restricted by 8x8; no raw media access to third-party servers | **Supported**: Jigasi / `opus-transcriber-proxy` | **Supported**: JaaS webhook transcription |
| **Browser Audio Path** | Direct authorized mic streaming to FastAPI | Direct mic or bridge transcription | Direct mic or bridge transcription |
| **Recommended Use** | Local development, rapid testing, demos | Enterprise on-premise, HIPAA, strict privacy | Scalable managed production |

> [!IMPORTANT]
> **Real Meeting Audio & Transcription Infrastructure**:
> The free public cluster `meet.jit.si` does not allow third-party backends to tap remote participant audio streams directly from browser iframes due to WebRTC security and cross-origin boundaries.
> To transcribe speech from **both** participants in a real Jitsi meeting, configure `JITSI_BRIDGE_PROVIDER` in `.env`:
> - `jaas`: 8x8 JaaS (Jitsi as a Service). Provides native server-side transcription and dispatches signed `TRANSCRIPTION_CHUNK` webhooks (`X-8x8-Signature`).
> - `jigasi`: Self-hosted Jitsi instance with Jigasi or `opus-transcriber-proxy`. Taps JVB audio for all participants and posts HMAC-signed transcript segments (`X-Jitsi-Signature`).
> - `none`: Local microphone capture or development testing only.
>
> All transcript segments are immutably tagged with their `source`: `bridge`, `local_microphone`, or `simulation`. The finalized evaluation report includes a verified `transcript_provenance` breakdown. Development simulation endpoints are strictly forbidden (`403 Forbidden`) in production.

### 3. Step-by-Step: Running a Two-Person Test Meeting

1. **Start the Application**:
   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```
2. **Open the Dashboard**:
   Navigate to `http://localhost:8000/interview-dashboard` in Chrome or Edge.
3. **Create Session**:
   Click `+ New Session` in the top toolbar. A new interview session ID is generated.
4. **Start Jitsi Meeting**:
   Click `🎥 Jitsi Meet`. The dashboard fetches room configuration and embeds the Jitsi call with camera and microphone controls.
5. **Invite Candidate**:
   Click `🔗 Candidate Link`. Copy the candidate join URL and open it in another browser window (or incognito window).
6. **Join and Interact**:
   Both participants can see and speak to each other via WebRTC.
7. **Ingest Real Transcript Events**:
   - **For Jitsi Bridge Ingestion**: Click `⚡ Test Jitsi Bridge` to ingest realistic multi-turn dialogue directly through the Jitsi Transcription Adapter into PostgreSQL.
   - **For Live Microphone Ingestion**: Click `🎙️ Live Mic Stream`, review the consent disclosure, and speak into your microphone.
8. **View Generated Notes**:
   Observe structured notes, key technical concepts, and question evaluations updating in real time via WebSockets.
9. **Finalize and Export**:
   Click `📋 Finalize & Report`. The executive report is synthesized with:
   - Interview Title & Meeting Date
   - Verified Participants
   - Executive Summary
   - Question-wise Discussion Summaries & Timestamps
   - Key Demonstrated Strengths & Areas for Growth
   - Technical Concepts Discussed
   - Decisions and Follow-up Actions
   - Unanswered / Unclear Discussion Points
   Export as JSON or GitHub Markdown.

### 4. Verifying Real Transcript Ingestion in PostgreSQL

Verify transcript persistence in PostgreSQL or SQLite using `psql` or SQL queries:

```sql
-- Verify session and associated Jitsi room
SELECT session_id, title, status, session_metadata->>'jitsi_room_name' AS jitsi_room
FROM interview_sessions;

-- Verify ingested transcript segments from Jitsi
SELECT segment_id, speaker_name, speaker_role, start_time, end_time, text, sequence_number
FROM interview_transcript_segments
ORDER BY start_time ASC;

-- Verify automated notes grounded in transcript
SELECT note_id, question_text, key_concepts, follow_up_points
FROM interview_notes;

-- Verify final report
SELECT report_id, aggregate_score, technical_concepts_discussed, decisions_and_actions
FROM interview_final_reports;
```

---
*Created with ❤️ for Advanced Online Assessment.*
