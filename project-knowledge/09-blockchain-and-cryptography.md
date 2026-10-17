# 09 - Blockchain & Cryptography

## 1. Applicability Status
* **Blockchain Technologies**: **Not Applicable (None in repository)**.
* **Smart Contracts**: None.
* **Web3 / Wallets**: None.

---

## 2. Cryptographic Analysis of Current Implementation

### Base64 Encoding
* Uses standard RFC 4648 Base64 encoding via Python's built-in `base64.b64decode()` and JavaScript's `HTMLCanvasElement.toDataURL()`.
* **Security Note**: Base64 is an encoding mechanism, not encryption. Raw webcam frames are transmitted in plaintext over HTTP if TLS is not enabled at the transport layer.

---

## 3. Recommended Cryptographic Hardening for Production

If deploying this microservice to high-stakes examinations, the following cryptographic mechanisms are recommended:

### A. HMAC Frame Signing (Anti-Tampering)
To prevent candidates from submitting pre-recorded "fake webcam" video streams using virtual camera drivers or automated HTTP injection scripts:
1. The exam portal issues a short-lived cryptographic nonce / challenge to the client every 2 seconds.
2. The client signs the frame hash with an HMAC secret:
   $$\text{Signature} = \text{HMAC-SHA256}(\text{SessionSecret}, \text{FrameBytes} \parallel \text{Nonce} \parallel \text{Timestamp})$$
3. The FastAPI microservice verifies the HMAC before running inference.

### B. Audit Trail Hashing (Immutable Proof)
For academic tribunals or dispute resolution, incident frames can be hashed (SHA-256) and anchored to an immutable ledger or append-only log so neither students nor administrators can forge evidence post-exam.
