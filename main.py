from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from api.routes import router as proctor_router
from interview_agent.api import interview_router
from interview_agent.config import settings
import uvicorn
import os

# Validate security configuration for production deployments
settings.validate_production_security()

# Suppress TensorFlow logging

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' 

app = FastAPI(title="AI Proctoring Backend Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Existing proctoring route registration (preserved intact)
app.include_router(proctor_router, prefix="/api/v1")

# Independent Interview Intelligence Agent router
app.include_router(interview_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": "AI Proctoring Service is running",
        "test_ui": "/test",
        "interview_dashboard": "/interview-dashboard"
    }

@app.get("/health")
@app.get("/api/v1/health")
async def health_check():
    """
    Standard HTTP health check endpoint for container orchestrators (Kubernetes, ECS).
    Verifies service liveness and database connectivity without exposing secrets or connection URLs.
    """
    db_ok = True
    if settings.persistence_backend == "postgres":
        try:
            from interview_agent.db.connection import check_db_health
            db_ok = check_db_health()
        except Exception:
            db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "environment": settings.app_env,
        "auth_mode": "jwt_verified" if (settings.jwt_jwks_url or settings.jwt_public_key or settings.jwt_secret) else "api_key"
    }

@app.get("/test")
async def test_ui():
    return FileResponse("test_frontend.html")

@app.get("/interview-dashboard")
async def interview_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "interview_agent", "static", "interview_dashboard.html")
    return FileResponse(dashboard_path)

if __name__ == "__main__":
    # Use reload=False to avoid issues with MediaPipe initialization in some environments
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
