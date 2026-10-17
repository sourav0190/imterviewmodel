# 07 - API Reference

This document provides verified documentation for all endpoints exposed by the AI Proctoring Backend Service.

---

### 1. Health Status Endpoint

* **Method**: `GET`
* **Path**: `/`
* **Authentication**: None
* **Description**: Verifies that the microservice is running and accessible.

#### Response:
* **Status Code**: `200 OK`
* **Content-Type**: `application/json`
```json
{
  "message": "AI Proctoring Service is running",
  "test_ui": "/test"
}
```

#### Example cURL:
```bash
curl -X GET http://localhost:8000/
```

---

### 2. Interactive Testing Dashboard Endpoint

* **Method**: `GET`
* **Path**: `/test`
* **Authentication**: None
* **Description**: Serves the standalone browser dashboard (`test_frontend.html`) for webcam testing.

#### Response:
* **Status Code**: `200 OK`
* **Content-Type**: `text/html; charset=utf-8`
* **Body**: Full HTML/JavaScript dashboard.

---

### 3. Frame Analysis & Proctoring Diagnostic Endpoint

* **Method**: `POST`
* **Path**: `/api/v1/analyze`
* **Authentication**: None (Open access)
* **Description**: Primary proctoring endpoint. Ingests a single base64-encoded webcam frame, runs the detection ensemble, and returns real-time behavioral diagnostics.

#### Request Headers:
```http
Content-Type: application/json
```

#### Request Payload:
```json
{
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD..."
}
```
* Note: The `image` property accepts raw base64 or base64 prefixed with standard Data URL schemes (`data:image/jpeg;base64,...` or `data:image/png;base64,...`).

#### Success Response:
* **Status Code**: `200 OK`
* **Content-Type**: `application/json`

```json
{
  "face_present": true,
  "multiple_people": false,
  "person_count": 1,
  "phone_detected": false,
  "book_detected": false,
  "looking_away": false,
  "gaze_direction": "Center",
  "pitch_score": 0.05,
  "is_talking": false,
  "hands_count": 2,
  "suspicion_score": 0,
  "malpractices": []
}
```

#### Incident Detection Response Example (Violations Detected):
* **Status Code**: `200 OK`
```json
{
  "face_present": true,
  "multiple_people": true,
  "person_count": 2,
  "phone_detected": true,
  "book_detected": false,
  "looking_away": true,
  "gaze_direction": "Down",
  "pitch_score": 0.72,
  "is_talking": true,
  "hands_count": 3,
  "suspicion_score": 100,
  "malpractices": [
    "Multiple people detected (2 persons)",
    "Mobile phone detected in frame",
    "Suspiciously looking down (Potential hidden notes)",
    "Mouth movement detected (Talking/Whispering)",
    "Suspicious hand count: 3 hands detected (Possible assistance)"
  ]
}
```

#### Field Definitions:
| Field | Type | Description |
| :--- | :--- | :--- |
| `face_present` | boolean | `true` if candidate's face is recognized in frame; `false` if obscured or absent. |
| `multiple_people` | boolean | `true` if more than 1 person is detected by YOLO. |
| `person_count` | integer | Total number of human bodies detected in frame. |
| `phone_detected` | boolean | `true` if a mobile phone / smartphone is identified. |
| `book_detected` | boolean | `true` if an open book, notebook, or cheat-sheet is identified. |
| `looking_away` | boolean | `true` if gaze or head pose deviates significantly from screen. |
| `gaze_direction` | string | Current estimated gaze direction: `"Center"`, `"Left"`, `"Right"`, `"Up"`, `"Down"`. |
| `pitch_score` | float | Vertical head tilt normalized score (positive = down, negative = up). |
| `is_talking` | boolean | `true` if jaw displacement exceeds resting threshold (`> 0.08`). |
| `hands_count` | integer | Total hands currently detected in camera view. |
| `suspicion_score` | integer | Cumulative behavioral risk score normalized between `0` and `100`. |
| `malpractices` | array of strings | Human-readable descriptions of all active infractions in the frame. |

---

### 4. Error Responses

#### A. Invalid Image Data (Corrupted or Non-Image Base64)
* **Status Code**: `400 Bad Request`
```json
{
  "detail": "Invalid image data"
}
```

#### B. Malformed JSON / Missing Field
* **Status Code**: `422 Unprocessable Entity`
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "image"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```
