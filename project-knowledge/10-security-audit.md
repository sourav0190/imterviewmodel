# 10 - Security & Integrity Audit

This security audit inspects input validation, access controls, network boundaries, abuse scenarios, and model reliability.

---

### 1. Summary of Vulnerability Classifications

| ID | Title | Severity | Location | Status |
| :--- | :--- | :---: | :--- | :--- |
| **SEC-01** | Completely Unauthenticated Public API | **HIGH** | `api/routes.py` | Present |
| **SEC-02** | Absence of Rate Limiting / Compute Exhaustion DoS | **HIGH** | `main.py`, `api/routes.py` | Present |
| **SEC-03** | Overly Permissive Wildcard CORS Configuration | **MEDIUM** | `main.py:L14` | Present |
| **SEC-04** | Unbounded Base64 String Memory Ingestion | **MEDIUM** | `utils/image_utils.py` | Present |
| **SEC-05** | Vulnerability to Virtual Camera Spoofing (OBS/ManyCam) | **MEDIUM** | Architecture Level | Present |
| **SEC-06** | Variable Scope Bug on Incomplete Face Landmarks | **LOW** | `face_landmark_detector.py:L83` | Present |
| **SEC-07** | Plaintext HTTP Exposure by Default | **LOW** | `main.py:L28` | Present |

---

### 2. In-Depth Vulnerability Analysis & Remediation

#### SEC-01: Completely Unauthenticated Public API
* **Severity**: **HIGH**
* **Evidence**:
  ```python
  # api/routes.py
  @router.post("/analyze")
  async def analyze_frame(data: FrameData):
  ```
* **Impact**: The endpoint does not check for API keys, bearer tokens, or session headers. Any attacker who discovers the server IP/domain can send arbitrary frames, consume server CPU/RAM, and hijack inference resources.
* **Remediation**: Implement a JWT or API Key header check using FastAPI's `Security(HTTPBearer())`:
  ```python
  from fastapi import Security, HTTPException, status
  from fastapi.security import APIKeyHeader

  API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

  def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
      if api_key != os.getenv("PROCTOR_API_KEY"):
          raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
  ```

---

#### SEC-02: Absence of Rate Limiting / Compute Exhaustion DoS
* **Severity**: **HIGH**
* **Evidence**: No rate limiting middleware (e.g., `slowapi`, Redis token bucket, or Cloudflare reverse proxy rules) exists in `main.py`.
* **Impact**: Running YOLO and MediaPipe takes ~50ms of CPU time. Sending 100 concurrent requests per second will drive CPU usage to 100%, causing request timeouts for legitimate students.
* **Remediation**: Enforce rate limiting of 1 request every 1.5 seconds per IP/session using `slowapi`:
  ```python
  from slowapi import Limiter, _rate_limit_exceeded_handler
  from slowapi.util import get_remote_address

  limiter = Limiter(key_func=get_remote_address)
  app.state.limiter = limiter

  @router.post("/analyze")
  @limiter.limit("1/second")
  async def analyze_frame(...):
  ```

---

#### SEC-03: Overly Permissive Wildcard CORS Configuration
* **Severity**: **MEDIUM**
* **Evidence**:
  ```python
  # main.py
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
* **Impact**: Any malicious website visited by an authenticated proctor or administrator could make cross-origin requests to the microservice.
* **Remediation**: Restrict `allow_origins` to the trusted production domain(s) of the assessment portal (e.g., `allow_origins=["https://exam.myuniversity.edu"]`).

---

#### SEC-04: Unbounded Base64 String Memory Ingestion
* **Severity**: **MEDIUM**
* **Evidence**: `FrameData.image` has no maximum length constraint in Pydantic:
  ```python
  class FrameData(BaseModel):
      image: str
  ```
* **Impact**: An attacker can submit a 100MB string payload, causing severe memory allocation spikes during `base64.b64decode()`.
* **Remediation**: Constrain the string size using Pydantic's `Field(max_length=...)` (a 640x480 JPEG at 80% quality is rarely larger than 150KB, or ~200KB base64):
  ```python
  class FrameData(BaseModel):
      image: str = Field(..., max_length=500_000) # Max 500 KB
  ```

---

#### SEC-05: Vulnerability to Virtual Camera Spoofing (OBS/ManyCam)
* **Severity**: **MEDIUM**
* **Evidence**: The client uses standard `navigator.mediaDevices.getUserMedia({ video: true })` without inspecting virtual camera hardware signatures or enforcing WebRTC device enumeration filters.
* **Impact**: A candidate can route a pre-recorded loop of themselves staring at the screen into OBS Virtual Camera, while looking at notes off-camera.
* **Remediation**: Add client-side hardware device verification:
  ```javascript
  const devices = await navigator.mediaDevices.enumerateDevices();
  const isVirtual = devices.some(d => /virtual|obs|manycam|v4l2loopback/i.test(d.label));
  if (isVirtual) alert("Virtual webcams are prohibited!");
  ```

---

### 3. Positive Security Controls Found
1. **Zero Biometric Persistence**: The service does not store facial embeddings, identities, or raw video streams on disk. Once inference completes, buffers are freed, complying with GDPR/FERPA guidelines.
2. **Safe Decoding Exception Handling**: [`utils/image_utils.py`](file:///c:/Users/soura/Desktop/hackshift/utils/image_utils.py#L18) wraps decoding in a `try-except` block, preventing unhandled exceptions from terminating the server process.
