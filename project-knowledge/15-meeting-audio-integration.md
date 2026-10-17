# Meeting-Audio Integration Architecture & Pipeline

## 1. Meeting Infrastructure Status & Topology

### Repository State Assessment
- **Existing Meeting Media Infrastructure:** The repository does **not** contain an embedded WebRTC SFU (Selective Forwarding Unit such as LiveKit, Mediasoup, or Janus) or native server-side meeting bot (e.g. headless Zoom/Teams bot container).
- **Client Frontend:** Browser-based interface (`/interview-dashboard`) with integrated `MediaStream` / `MediaRecorder` capture and real-time audio visualization.
- **Backend Transport:** REST streaming chunk ingestion via `POST /api/v1/interviews/{session_id}/audio` backed by per-stream bounded jitter buffering and real-time event distribution via `WebSocket /api/v1/interviews/ws/{session_id}`.

---

## 2. Audio Ingestion Architecture

```
                                [Browser / WebRTC Client]
                                           │
                         getUserMedia() Microphone Stream
                                           │
                         AudioContext Meter & User Consent
                                           │
                        MediaRecorder (audio/webm;codecs=opus)
                                           │
                        POST /api/v1/interviews/{session_id}/audio
                                           │
                                           ▼
                       [PlatformMediaAudioAdapter]
        ┌──────────────────────────────────┴──────────────────────────────────┐
        │ 1. Participant Authorization & Role Anti-Spoofing                   │
        │ 2. Payload Validation & Base64 Decoding                             │
        │ 3. Sequence Deduplication ((participant_id, seq) check)             │
        │ 4. Bounded Jitter Buffer (Reordering & Gap Flushing)                 │
        │ 5. Container Normalization (PCM -> RIFF/WAV, WebM, MP3, OGG)        │
        │ 6. GDPR/Privacy Audio Retention Guard (Disabled by Default)         │
        └──────────────────────────────────┬──────────────────────────────────┘
                                           │
                                           ▼
                             [Transcription Engine]
                     ┌─────────────────────┴─────────────────────┐
                     │                                           │
          [MockTranscriptionService]               [WhisperTranscriptionService]
             (is_simulated = True)                    (is_simulated = False)
                     │                                           │
                     └─────────────────────┬─────────────────────┘
                                           │
                                           ▼
                             [InterviewSessionService]
        ┌──────────────────────────────────┴──────────────────────────────────┐
        │ • Append to session.transcript_segments                             │
        │ • Real-time WebSocket Broadcast ("transcript_segment")             │
        │ • QuestionDetector (Question tracking & turn finalization)          │
        │ • NotesService (Structured candidate notes)                         │
        │ • AnswerEvaluator (Rubric-aligned question scoring)                 │
        │ • Persistence to In-Memory & PostgreSQL via SQLAlchemy / Alembic    │
        └─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Key Pipeline Components

### 3.1 Participant Authorization & Role Anti-Spoofing
- Ingestion checks that `chunk.participant_id` matches a registered participant in the session.
- Client-supplied `participant_role` is checked against authoritative session records. If the client attempts to spoof roles (e.g., candidate sending `role="interviewer"`), the backend overrides it with the authoritative role.

### 3.2 Bounded Jitter Buffer (`BoundedJitterBuffer`)
- Reorders out-of-order arriving chunks per `(session_id, participant_id)` stream.
- Maintains strict O(1) bounded memory with `max_buffer_size = 20`.
- Implements gap-flushing backpressure defense (`max_gap = 5`) to prevent pipeline stalling when missing packets are permanently lost in network transit.

### 3.3 Container Normalization & Formatting
- Standardizes raw Linear PCM (16-bit little-endian) by synthesizing valid in-memory RIFF/WAVE headers using Python standard `wave` library.
- Preserves native containers (`audio/webm`, `audio/mpeg`, `audio/ogg`, `audio/flac`) with appropriate MIME types for direct ingestion by speech-to-text engines (e.g., OpenAI Whisper API or local Whisper models).

### 3.4 Transcription Provenance
- `TranscriptSegment.is_simulated` explicitly distinguishes simulated/mock outputs (`True`) from verified live model outputs (`False`).

### 3.5 Speaker Attribution Strategy
- Primary: Track-level deterministic mapping based on discrete participant audio tracks.
- Fallback: Conversational turn-taking state machine in `SpeakerService` when participant ID is missing or track multiplexed.

---

## 4. Environment Configuration

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `TRANSCRIPTION_PROVIDER` | `mock` | `mock` or `whisper` |
| `OPENAI_API_KEY` | None | Required when `TRANSCRIPTION_PROVIDER=whisper` |
| `WHISPER_MODEL` | `whisper-1` | Model name for Whisper STT |
| `AUDIO_RETENTION_ENABLED`| `False` | Privacy compliance; must remain false unless explicit legal consent is obtained |
| `AUDIO_STORAGE_PATH` | `./storage/audio` | Safe filesystem root for retained audio (protected against path traversal) |
| `AUDIO_JITTER_BUFFER_MAX_CHUNKS` | `20` | Max packet buffer capacity per stream |
| `AUDIO_MAX_CHUNK_GAP` | `5` | Maximum gap tolerance before flushing missing sequences |

---

## 5. Verification Summary
- Full test suite: `tests/test_meeting_audio_integration.py` (15 tests) + existing suites (38 tests) = **53 tests passing**.
- Real microphone streaming tested via browser `MediaRecorder` on `/interview-dashboard`.
