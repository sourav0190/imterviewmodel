# 04 - Frontend Architecture & Components

The repository provides three frontend implementations:
1. **Interactive Test Dashboard** ([`test_frontend.html`](file:///c:/Users/soura/Desktop/hackshift/test_frontend.html)): Standalone HTML5 + Vanilla JS dashboard for direct browser testing.
2. **Modular React Panel** ([`ProctoringPanel.jsx`](file:///c:/Users/soura/Desktop/hackshift/ProctoringPanel.jsx)): Reusable React component with callbacks.
3. **Reference Integration Script** ([`frontend_integration_example.js`](file:///c:/Users/soura/Desktop/hackshift/frontend_integration_example.js)): Demonstration using the `react-webcam` package.

---

### 1. `test_frontend.html` (Standalone Dashboard)

#### Architecture & DOM Elements
* **Styling**: Sleek dark-mode interface (`#0b0e14` background, `#1e293b` cards) with responsive flex layout.
* **Key Elements**:
  * `<video id="webcam">`: Displays the live webcam stream, horizontally mirrored (`transform: scaleX(-1)`).
  * `<canvas id="canvas">`: Hidden off-screen canvas (`width=640`, `height=480`) used to rasterize video frames for base64 extraction.
  * `<div class="overlay-status">`: Displays current state pill (`STANDBY`, `MONITORING`, or `SUSPICIOUS`) with pulsing indicator (`#status-pulse`).
  * `<div class="stat-grid">`: Four live diagnostic boxes displaying Face Presence, People Count, Gaze Direction, and Talking Status.
  * `<div class="suspicion-bar">`: Animated progress bar (`#suspicion-fill`) with color transition (Green $\to$ Amber $\to$ Red).
  * `<div id="malpractice-list">`: Live list dynamically populated with active infraction warnings.
  * `<button id="toggle-btn">`: Starts or stops the proctoring loop.

#### Lifecycle & Execution Flow
1. **Camera Initialization (`init()`)**:
   ```javascript
   const stream = await navigator.mediaDevices.getUserMedia({
       video: { width: 640, height: 480 }
   });
   video.srcObject = stream;
   ```
2. **Frame Capture & Analysis Loop (`process()`)**:
   - Checks `if (!isMonitoring) return;`
   - Draws video frame: `context.drawImage(video, 0, 0, 640, 480);`
   - Encodes to JPEG: `canvas.toDataURL('image/jpeg', 0.8);`
   - Sends HTTP POST to `http://localhost:8000/api/v1/analyze`.
   - Calls `render(data)` to update DOM elements.
3. **Event Listener**:
   - `toggleBtn.addEventListener('click')` toggles `isMonitoring` state.
   - Triggers `setInterval(process, 1500)` when active, or `clearInterval(intervalId)` when stopped.

---

### 2. `ProctoringPanel.jsx` (Reusable React Component)

* **Props**:
  * `apiUrl`: URL of the deployed microservice endpoint (default: `http://localhost:8000/api/v1/analyze`).
  * `onStatusUpdate`: Callback function sending full proctoring reports to the parent application.
* **Component State**:
  * `isMonitoring`: Boolean flag controlling active frame dispatch.
  * `report`: Stores the latest API response dictionary.
* **Hooks Used**:
  * `useRef`: `videoRef`, `canvasRef`, and `intervalRef` manage DOM references without causing re-renders.
  * `useEffect`: Starts webcam on component mount; stops interval on unmount.
* **Parent Page Usage**:
  ```jsx
  <ProctoringPanel 
      apiUrl="http://localhost:8000/api/v1/analyze" 
      onStatusUpdate={(report) => {
          if (report.suspicion_score > 70) {
              console.warn("Candidate flagged!");
          }
      }}
  />
  ```

---

### 3. Frontend Gaps & Identified Quirks
1. **Missing `'use client'` Directive**: Both `ProctoringPanel.jsx` and `frontend_integration_example.js` use React client hooks (`useState`, `useEffect`, `useRef`) but omit `'use client'`, causing compiler failures in Next.js App Router (`app/` directory).
2. **Mirror Inversion**: `scaleX(-1)` mirrors video visually for user familiarity, but canvas rasterization captures raw un-mirrored frames. This means a candidate looking right appears as "Left" in the detector.
3. **Unbounded `setInterval`**: If inference time exceeds 1.5 seconds, `setInterval` continues sending frames, creating a memory and HTTP queue backlog.
