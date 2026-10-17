# 13 - Technical Glossary

This glossary explains key computer vision, deep learning, and architectural terms used throughout the codebase.

---

### 1. Computer Vision & Machine Learning Terms

* **Blendshapes**:
  * *Simple*: Virtual facial sliders (like in video games or 3D animation) that measure how much an eye is looking sideways or a mouth is open from 0 to 1.
  * *Technical*: Coefficients of a linear combination of basis facial meshes representing Action Units (e.g., `jawOpen`, `eyeLookInLeft`, `eyeLookDownRight`).
* **Canonical Face Mesh**:
  * *Simple*: A standard 3D map of a human face with dots on the nose, eyes, lips, and jaw.
  * *Technical*: A normalized 3D template containing 478 vertices representing facial surface topology independent of distance from camera.
* **COCO Dataset (Common Objects in Context)**:
  * *Simple*: A massive library of over 300,000 photos labeled with everyday objects used to teach AI to recognize items like people, laptops, and phones.
  * *Technical*: Benchmark dataset containing 80 object categories used for training object detection and instance segmentation models.
* **Confidence Threshold**:
  * *Simple*: The minimum certainty percentage the AI must have before reporting that an object is present (e.g., 0.20 = 20% certainty).
  * *Technical*: Bounding box filtering parameter where detections with class confidence below the threshold are pruned.
* **Decoupled Head**:
  * *Simple*: Splitting a neural network's final job so one part finds *where* the object is and another part figures out *what* it is.
  * *Technical*: Architecture separating classification loss (BCE) from bounding box regression loss (CIoU / DFL) to prevent gradient interference.
* **Non-Maximum Suppression (NMS)**:
  * *Simple*: Cleaning up messy overlapping boxes so you only see one clean box around a person or phone instead of five.
  * *Technical*: Post-processing algorithm that eliminates redundant candidate bounding boxes sharing high Intersection-over-Union (IoU) with the top-scoring box.
* **Pitch (Head/Gaze)**:
  * *Simple*: Tilting your head or eyes up towards the ceiling or down towards your lap/keyboard.
  * *Technical*: Rotational movement about the lateral horizontal axis.
* **Yaw (Head/Gaze)**:
  * *Simple*: Turning your head or glancing with your eyes to the left or right.
  * *Technical*: Rotational movement about the vertical axis.
* **YOLO (You Only Look Once)**:
  * *Simple*: A fast object-detection algorithm that inspects an entire image in a single pass instead of scanning small sections repeatedly.
  * *Technical*: Single-stage CNN object detector predicting bounding boxes and class probabilities directly from full feature maps.

---

### 2. Software & Architecture Terms

* **Base64 Encoding**:
  * *Simple*: Converting binary image files into long text strings so they can be easily sent over normal HTTP web requests.
  * *Technical*: Binary-to-text encoding scheme representing binary data in an ASCII string format using 64 printable characters.
* **CORS (Cross-Origin Resource Sharing)**:
  * *Simple*: A browser security rule that dictates whether a webpage on one domain (like `http://localhost:3000`) is allowed to talk to a server on another (like `http://localhost:8000`).
  * *Technical*: HTTP header mechanism allowing servers to specify which external origins are permitted to access their resources.
* **Microservice**:
  * *Simple*: A small, focused backend program that does one specific job (in this case, analyzing webcam frames) and talks to other web apps via an API.
  * *Technical*: Architectural style structuring an application as a collection of loosely coupled, independently deployable services.
* **Statelessness**:
  * *Simple*: The server doesn't remember previous requests. Every picture sent to it is treated as brand-new without looking up past history.
  * *Technical*: Server design pattern where requests contain all necessary context and no client session state is retained on the server between calls.
* **Uvicorn**:
  * *Simple*: The fast engine that powers the Python FastAPI web server.
  * *Technical*: Lightning-fast ASGI (Asynchronous Server Gateway Interface) web server implementation for Python.
