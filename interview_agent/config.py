import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load any custom .env configuration if present
load_dotenv()

class InterviewConfig(BaseModel):
    """Configuration for Interview Intelligence Agent."""
    
    # Environment
    app_env: str = Field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    
    # LLM Settings
    llm_provider: str = Field(default_factory=lambda: os.getenv("INTERVIEW_LLM_PROVIDER", "mock"))
    llm_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("INTERVIEW_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    llm_base_url: Optional[str] = Field(default_factory=lambda: os.getenv("INTERVIEW_LLM_BASE_URL", None))
    llm_model: str = Field(default_factory=lambda: os.getenv("INTERVIEW_LLM_MODEL", "gpt-4o-mini"))
    llm_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("INTERVIEW_LLM_TIMEOUT_SECONDS", "30.0")))
    llm_max_retries: int = Field(default_factory=lambda: int(os.getenv("INTERVIEW_LLM_MAX_RETRIES", "2")))
    llm_max_concurrency: int = Field(default_factory=lambda: int(os.getenv("INTERVIEW_LLM_MAX_CONCURRENCY", "3")))
    
    # Speech-to-Text (STT) Settings
    stt_provider: str = Field(default_factory=lambda: os.getenv("INTERVIEW_STT_PROVIDER") or os.getenv("TRANSCRIPTION_PROVIDER", "mock"))
    stt_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("INTERVIEW_STT_API_KEY") or os.getenv("OPENAI_API_KEY"))
    stt_model: str = Field(default_factory=lambda: os.getenv("INTERVIEW_STT_MODEL", "whisper-1"))
    stt_language: str = Field(default_factory=lambda: os.getenv("INTERVIEW_STT_LANGUAGE", "en"))
    
    # Audio Security and Retention Policies
    # GDPR & Privacy: Raw audio is NEVER retained by default
    audio_retention_enabled: bool = Field(
        default_factory=lambda: os.getenv("INTERVIEW_AUDIO_RETENTION_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    audio_storage_path: str = Field(default_factory=lambda: os.getenv("INTERVIEW_AUDIO_STORAGE_PATH", "storage/interview_audio"))
    max_audio_chunk_bytes: int = Field(default_factory=lambda: int(os.getenv("INTERVIEW_MAX_AUDIO_CHUNK_BYTES", str(2 * 1024 * 1024)))) # 2MB
    audio_jitter_buffer_max_chunks: int = Field(default_factory=lambda: int(os.getenv("INTERVIEW_AUDIO_JITTER_BUFFER_MAX", "20")))
    audio_max_chunk_gap: int = Field(default_factory=lambda: int(os.getenv("INTERVIEW_AUDIO_MAX_CHUNK_GAP", "5")))
    
    # Security / Auth
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("INTERVIEW_API_KEY", None))
    allow_anonymous_dev: bool = Field(
        default_factory=lambda: (
            False if os.getenv("APP_ENV", "development").lower() in ("production", "prod")
            else os.getenv("INTERVIEW_ALLOW_ANONYMOUS_DEV", "true").lower() in ("true", "1", "yes")
        )
    )

    # JWT & Identity Provider Configuration
    jwt_auth_enabled: bool = Field(
        default_factory=lambda: os.getenv("JWT_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    jwt_issuer: Optional[str] = Field(default_factory=lambda: os.getenv("JWT_ISSUER", None))
    jwt_audience: Optional[str] = Field(default_factory=lambda: os.getenv("JWT_AUDIENCE", None))
    jwt_jwks_url: Optional[str] = Field(default_factory=lambda: os.getenv("JWT_JWKS_URL", None))
    jwt_public_key: Optional[str] = Field(default_factory=lambda: os.getenv("JWT_PUBLIC_KEY", None))
    jwt_secret: Optional[str] = Field(default_factory=lambda: os.getenv("JWT_SECRET", None))
    jwt_algorithms: list = Field(
        default_factory=lambda: [a.strip() for a in os.getenv("JWT_ALGORITHMS", "RS256,ES256,HS256").split(",") if a.strip()]
    )
    ws_ticket_expiry_seconds: int = Field(
        default_factory=lambda: int(os.getenv("WS_TICKET_EXPIRY_SECONDS", "60"))
    )

    # CORS Settings
    cors_allowed_origins: list = Field(
        default_factory=lambda: [
            o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if o.strip()
        ]
    )

    # Jitsi Meet Integration Settings
    jitsi_server_url: str = Field(default_factory=lambda: os.getenv("JITSI_SERVER_URL", "https://meet.jit.si").rstrip("/"))
    jitsi_domain: str = Field(default_factory=lambda: os.getenv("JITSI_DOMAIN", "meet.jit.si"))
    jitsi_room_prefix: str = Field(default_factory=lambda: os.getenv("JITSI_ROOM_PREFIX", "AiProtctor-Interview"))
    jitsi_webhook_secret: Optional[str] = Field(default_factory=lambda: os.getenv("JITSI_WEBHOOK_SECRET", None))
    jitsi_app_id: Optional[str] = Field(default_factory=lambda: os.getenv("JITSI_APP_ID", None))
    jitsi_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("JITSI_API_KEY", None))
    jitsi_secret: Optional[str] = Field(default_factory=lambda: os.getenv("JITSI_SECRET", None))
    jitsi_transcription_service_url: Optional[str] = Field(default_factory=lambda: os.getenv("JITSI_TRANSCRIBER_URL", None))
    jitsi_transcription_enabled: bool = Field(
        default_factory=lambda: os.getenv("JITSI_TRANSCRIPTION_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    # Jitsi Transcription Bridge Provider
    # Options: "none" (default, public meet.jit.si without external bridge),
    #          "jigasi" (self-hosted Jitsi with Jigasi or opus-transcriber-proxy),
    #          "jaas" (8x8 Jitsi as a Service transcription webhooks)
    jitsi_bridge_provider: str = Field(
        default_factory=lambda: os.getenv("JITSI_BRIDGE_PROVIDER", "none").lower()
    )

    # Persistence / Database Configuration
    # Supported: "postgres" (SQLAlchemy/PostgreSQL or SQLite), "memory" (test/dev explicit in-memory)
    database_url: Optional[str] = Field(default_factory=lambda: os.getenv("DATABASE_URL", None))
    persistence_backend: str = Field(
        default_factory=lambda: os.getenv(
            "INTERVIEW_PERSISTENCE_BACKEND",
            "postgres" if os.getenv("DATABASE_URL") or os.getenv("APP_ENV", "development").lower() in ("production", "prod") else "memory"
        )
    )

    def validate_production_security(self):
        """Fails startup safely if required production security settings are missing."""
        if self.app_env.lower() in ("production", "prod"):
            has_jwt = bool(self.jwt_jwks_url or self.jwt_public_key or self.jwt_secret)
            has_api_key = bool(self.api_key)
            if not has_jwt and not has_api_key:
                raise ValueError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Either verified JWT configuration (JWT_JWKS_URL / JWT_PUBLIC_KEY / JWT_SECRET) or INTERVIEW_API_KEY must be configured in production."
                )
            if self.allow_anonymous_dev:
                raise ValueError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: INTERVIEW_ALLOW_ANONYMOUS_DEV cannot be enabled in production."
                )
            if "*" in self.cors_allowed_origins:
                raise ValueError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Wildcard CORS origin ('*') is prohibited in production when credentials are enabled. Configure explicit origins in CORS_ALLOWED_ORIGINS."
                )
            if not self.database_url:
                raise ValueError(
                    "CRITICAL DATABASE CONFIGURATION ERROR: DATABASE_URL must be configured in production."
                )
            if self.persistence_backend != "postgres":
                raise ValueError(
                    "CRITICAL DATABASE CONFIGURATION ERROR: In-memory persistence is prohibited in production. Set INTERVIEW_PERSISTENCE_BACKEND=postgres."
                )
            if self.stt_provider.lower() == "whisper" and not self.stt_api_key:
                raise ValueError(
                    "CRITICAL CONFIGURATION ERROR: INTERVIEW_STT_PROVIDER is 'whisper' but no STT API key is configured."
                )
            if self.llm_provider.lower() == "openai" and not self.llm_api_key:
                raise ValueError(
                    "CRITICAL CONFIGURATION ERROR: INTERVIEW_LLM_PROVIDER is 'openai' but no LLM API key is configured."
                )

            # Jitsi Transcription Bridge validation for production
            if self.jitsi_bridge_provider == "jaas":
                if not self.jitsi_app_id:
                    raise ValueError(
                        "CRITICAL JITSI CONFIGURATION ERROR: JITSI_BRIDGE_PROVIDER is 'jaas', but JITSI_APP_ID is missing. "
                        "8x8 JaaS requires an App ID (e.g. 'vpaas-magic-cookie-xxx')."
                    )
                if not (self.jitsi_api_key or self.jitsi_secret):
                    raise ValueError(
                        "CRITICAL JITSI CONFIGURATION ERROR: JITSI_BRIDGE_PROVIDER is 'jaas', but JITSI_API_KEY / JITSI_SECRET is missing. "
                        "JaaS authenticated rooms require signed meeting JWTs."
                    )
                if not self.jitsi_webhook_secret:
                    raise ValueError(
                        "CRITICAL JITSI CONFIGURATION ERROR: JITSI_BRIDGE_PROVIDER is 'jaas', but JITSI_WEBHOOK_SECRET is missing. "
                        "Cannot authenticate incoming 8x8 JaaS transcription webhook events."
                    )
            elif self.jitsi_bridge_provider == "jigasi":
                if not self.jitsi_webhook_secret:
                    raise ValueError(
                        "CRITICAL JITSI CONFIGURATION ERROR: JITSI_BRIDGE_PROVIDER is 'jigasi', but JITSI_WEBHOOK_SECRET is missing. "
                        "Cannot authenticate incoming bridge transcription callbacks."
                    )
                if self.jitsi_server_url == "https://meet.jit.si":
                    raise ValueError(
                        "CRITICAL JITSI CONFIGURATION ERROR: JITSI_BRIDGE_PROVIDER is 'jigasi', but JITSI_SERVER_URL is configured "
                        "as public 'https://meet.jit.si'. Jigasi requires a dedicated self-hosted Jitsi Meet deployment."
                    )
            elif self.jitsi_transcription_enabled and self.jitsi_bridge_provider == "none":
                raise ValueError(
                    "CRITICAL JITSI CONFIGURATION ERROR: JITSI_TRANSCRIPTION_ENABLED is true in production, but "
                    "JITSI_BRIDGE_PROVIDER is 'none'. Public meet.jit.si does not expose remote participant audio or transcripts "
                    "to external backends. Configure either JITSI_BRIDGE_PROVIDER=jaas (8x8 JaaS) or JITSI_BRIDGE_PROVIDER=jigasi (self-hosted)."
                )

    
    # Evaluation settings
    min_answer_duration_seconds: float = Field(
        default_factory=lambda: float(os.getenv("INTERVIEW_MIN_ANSWER_DURATION", "2.0"))
    )
    provisional_eval_delay_seconds: float = Field(
        default_factory=lambda: float(os.getenv("INTERVIEW_PROVISIONAL_EVAL_DELAY", "3.0"))
    )

settings = InterviewConfig()

