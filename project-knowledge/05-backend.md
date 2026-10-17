# 05 - Backend Architecture & Business Logic

The backend is built as an asynchronous Python microservice utilizing **FastAPI** and **Uvicorn**.

---

### 1. Server Configuration & Setup ([`main.py`](file:///c:/Users/soura/Desktop/hackshift/main.py))

* **FastAPI Application Initialization**:
  ```python
  app = FastAPI(title="AI Proctoring Backend Service")
  ```
* **CORS Middleware**: Configured with permissive parameters to facilitate cross-origin requests from Next.js, React, or local development ports:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
* **Sub-Routers**: Mounts proctoring endpoints at `/api/v1` prefix.
* **Environment Configuration**: Suppresses TensorFlow C++ verbose logs:
  ```python
  os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
  ```
* **Static / UI Endpoints**:
  * `GET /`: Health status JSON.
  * `GET /test`: Serves `test_frontend.html` via `FileResponse`.
* **Execution Guard**: Explicitly disables Uvicorn auto-reload (`reload=False`) to avoid crashing MediaPipe C++ bindings.

---

### 2. API Routes & Controller ([`api/routes.py`](file:///c:/Users/soura/Desktop/hackshift/api/routes.py))

#### Singleton Detector Initialization
To avoid reloading large neural network weights on every HTTP request, all models are instantiated once in memory at module import:
```python
landmark_detector = FaceLandmarkDetector()
person_phone_detector = PersonPhoneDetector()
hand_detector = HandDetector()
analyzer = BehaviorAnalyzer()
```

#### Request Validation
Uses Pydantic for automated payload validation:
```python
class FrameData(BaseModel):
    image: str # Base64 encoded JPEG string
```

#### Controller Execution Flow (`analyze_frame`)
1. **Decode Frame**:
   ```python
   frame = decode_base64_image(data.image)
   if frame is None:
       raise HTTPException(status_code=400, detail="Invalid image data")
   ```
2. **Execute Detectors**:
   - `face_gaze_results = landmark_detector.detect(frame)`
   - `person_results = person_phone_detector.detect(frame)`
   - `hand_results = hand_detector.detect(frame)`
3. **Execute Behavioral Analysis**:
   - `report = analyzer.analyze(face_gaze_results, person_results, hand_results)`
4. **Return JSON Response**: HTTP 200 with structured diagnostic report.

---

### 3. Business Logic Engine ([`services/behavior_analyzer.py`](file:///c:/Users/soura/Desktop/hackshift/services/behavior_analyzer.py))

The `BehaviorAnalyzer` class implements the rule-based risk weighting engine.

#### Infraction Penalties & Rule Set
| Rule | Condition | Penalty | Alert String |
| :--- | :--- | :---: | :--- |
| **Face Missing** | `not face_gaze_results["face_present"]` | **+40** | `"Face not detected (Candidate might have left or camera obscured)"` |
| **Multiple People** | `person_results["multiple_people"]` | **+50** | `"Multiple people detected ({count} persons)"` |
| **Mobile Phone** | `person_results["phone_detected"]` | **+60** | `"Mobile phone detected in frame"` |
| **Book / Notes** | `person_results.get("book_detected")` | **+45** | `"Notebook/Book/Cheat-sheet detected"` |
| **Secondary Laptop**| `person_results.get("laptop_detected")` | **+30** | `"Secondary screen/laptop detected"` |
| **Severe Look Down**| `direction == "Down"` and `pitch > 0.65` | **+30** | `"Suspiciously looking down (Potential hidden notes)"` |
| **Mild Look Down** | `direction == "Down"` and `pitch <= 0.65`| **+5** | *(No alert banner added; accounted as typing)* |
| **Looking Away** | `looking_away` and `direction != "Down"` | **+20** | `"Looking away from screen (Direction: {direction})"` |
| **Talking** | `face_gaze_results["is_talking"]` | **+15** | `"Mouth movement detected (Talking/Whispering)"` |
| **3+ Hands** | `hand_count > 2` | **+40** | `"Suspicious hand count: {count} hands detected (Possible assistance)"` |

#### Score Normalization
```python
final_score = min(score, 100)
```
Scores are strictly bound to $[0, 100]$ to provide a clean percentage index.

---

### 4. Utilities ([`utils/image_utils.py`](file:///c:/Users/soura/Desktop/hackshift/utils/image_utils.py))

* `decode_base64_image(base64_string)`:
  - Splits metadata headers if comma exists (`data:image/jpeg;base64,...`).
  - Decodes base64 string to bytes via `base64.b64decode()`.
  - Converts byte buffer to NumPy array via `np.frombuffer(encoded_data, np.uint8)`.
  - Decodes image matrix via `cv2.imdecode(..., cv2.IMREAD_COLOR)`.
  - Wraps execution in `try-except`, returning `None` on errors instead of raising uncaught exceptions.
* `encode_image_to_base64(image)`:
  - Encodes OpenCV matrix to JPEG buffer and converts to base64 string.
