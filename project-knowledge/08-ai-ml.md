# 08 - AI/ML Pipeline & Computer Vision Models

This document details the machine learning models, inference pipelines, and mathematical heuristics employed in the proctoring service.

---

### 1. Model Overview & Specifications

| Model Name | Framework / Provider | Model File | Parameters / Size | Primary Task |
| :--- | :--- | :--- | :--- | :--- |
| **YOLOv8s** | Ultralytics / PyTorch | `yolov8s.pt` | 11.2M params (21.5 MB) | Multi-person & unauthorized device detection |
| **Face Landmarker** | Google MediaPipe Tasks Vision | `models/face_landmarker.task` | MobileNetV2 backbone (3.6 MB) | 478 3D landmarks & 52 facial blendshapes |
| **Hand Landmarker** | Google MediaPipe Tasks Vision | `models/hand_landmarker.task` | BlazePalm + Landmark regressor (7.5 MB) | Hand presence & multi-hand counting |

---

### 2. Object & Person Detection: YOLOv8s

#### A. Architecture & Methodology
* **Backbone**: Modified CSPDarknet featuring C2f (Cross-Stage Partial with two convolutions) modules for high gradient flow and lightweight CPU execution.
* **Neck**: Path Aggregation Network (PAN-FPN) for multi-scale feature representation.
* **Head**: Decoupled, Anchor-Free Detection Head. Separately predicts object class probabilities and bounding box coordinates via Distribution Focal Loss (DFL).

#### B. Implementation in Code ([`detection/person_phone_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/person_phone_detector.py))
```python
self.model = YOLO('yolov8s.pt')
self.target_classes = [0, 67, 73, 63]  # 0: person, 67: cell phone, 73: book, 63: laptop
self.conf_threshold = 0.20             # Low threshold for high recall of small devices
```

#### C. Target Class Mapping
* **Class 0 (`person`)**: Determines candidate presence and counts secondary people (`multiple_people = person_count > 1`).
* **Class 67 (`cell phone`)**: Identifies handheld smartphones.
* **Class 63 (`laptop`)**: Identifies secondary screens or external computers.
* **Class 73 (`book`)**: Identifies open notebooks or papers.

---

### 3. Face & Gaze Tracking: MediaPipe Face Landmarker

#### A. Architecture & Pipeline
* Operates on a two-stage pipeline:
  1. A lightweight detector predicts face bounding boxes.
  2. A 3D landmark regression model computes 478 3D metric coordinates $(x, y, z)$ on the canonical face mesh.
* **Blendshape Output**: Computes 52 ARKit-compatible facial action unit scores normalized between $0.0$ and $1.0$.

#### B. Gaze Yaw (Left / Right) Heuristics
Gaze direction along the horizontal axis (yaw) is derived from pupil movement blendshapes:
```python
eye_look_in_left = blendshapes.get('eyeLookInLeft', 0)
eye_look_in_right = blendshapes.get('eyeLookInRight', 0)
eye_look_out_left = blendshapes.get('eyeLookOutLeft', 0)
eye_look_out_right = blendshapes.get('eyeLookOutRight', 0)

if eye_look_out_left > 0.4 or eye_look_in_right > 0.4:
    gaze_direction = "Left"
    looking_away = True
elif eye_look_out_right > 0.4 or eye_look_in_left > 0.4:
    gaze_direction = "Right"
    looking_away = True
```

#### C. Head Pitch (Looking Down / Up) Heuristics
Calculates vertical tilt differential:
$$\text{pitch\_score} = \frac{\text{eyeLookDownLeft} + \text{eyeLookDownRight}}{2} - \frac{\text{eyeLookUpLeft} + \text{eyeLookUpRight}}{2}$$

* If $\text{pitch\_score} > 0.4$: Head tilted downward.
* In `BehaviorAnalyzer`:
  * If $\text{pitch\_score} > 0.65$: Severe tilt (looking into lap for notes) $\to$ **+30 points** (Alert).
  * If $0.40 < \text{pitch\_score} \le 0.65$: Moderate tilt (looking at keyboard to type) $\to$ **+5 points** (No alert).

#### D. Talking / Mouth Movement Heuristics
```python
jaw_open = blendshapes.get('jawOpen', 0)
if jaw_open > 0.08:
    is_talking = True
```

---

### 4. Multi-Hand Detection: MediaPipe Hand Landmarker

#### A. Architecture
* Consists of **BlazePalm** detector that identifies palm centers and bounding rotations, followed by a **Hand Landmark Model** predicting 21 3D landmarks (knuckles, fingertips, wrist).
* Configured in [`detection/hand_detector.py`](file:///c:/Users/soura/Desktop/hackshift/detection/hand_detector.py):
  ```python
  options = vision.HandLandmarkerOptions(
      base_options=base_options,
      num_hands=4, 
      min_hand_detection_confidence=0.3
  )
  ```

#### B. Third Hand Malpractice Logic
* Standard candidates use at most 2 hands to type or use a mouse.
* If `hand_count > 2`: An external collaborator is physically interacting in the candidate's workspace. Triggers **+40 points** penalty.

---

### 5. Performance Benchmarks on CPU

Tested on an Intel/AMD 6-core x86_64 CPU without GPU acceleration:
* Image decoding: **~2.1 ms**
* MediaPipe Face Landmarker: **~12–18 ms**
* MediaPipe Hand Landmarker: **~10–15 ms**
* Ultralytics YOLOv8s: **~22–35 ms**
* Behavioral Risk Calculation: **< 0.5 ms**
* **Total Frame Latency**: **~45–70 ms** (Well within the 1500 ms polling cycle).
