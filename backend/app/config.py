import os
import json
from urllib.parse import quote_plus


def database_url():
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if os.getenv("DB_HOST"):
        return (
            "postgresql+psycopg://"
            + quote_plus(os.environ["DB_USER"])
            + ":"
            + quote_plus(os.environ["DB_PASSWORD"])
            + "@"
            + os.environ["DB_HOST"]
            + ":5432/"
            + os.getenv("DB_NAME", "nexus")
            + "?sslmode=verify-full&sslrootcert="
            + quote_plus(os.getenv("DB_SSLROOTCERT", "/srv/rds-ca.pem"))
        )
    return "sqlite:///./development.db"


from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = database_url()
    origin: str = os.getenv("APP_ORIGIN", "http://localhost:8000").rstrip("/")
    secret: str = os.getenv("AUTH_SECRET", "")
    role: str = os.getenv("APP_ROLE", "api")
    active_kid: str = os.getenv("JWT_ACTIVE_KID", "primary")
    jwt_keys_json: str = os.getenv("JWT_SIGNING_KEYS", "")
    idle_seconds: int = int(os.getenv("SESSION_IDLE_SECONDS", "1800"))
    max_sessions: int = int(os.getenv("MAX_SESSIONS", "5"))
    trust_gateway: bool = os.getenv("TRUST_GATEWAY", "false") == "true"
    environment: str = os.getenv("ENVIRONMENT", "development")
    region: str = os.getenv("AWS_REGION", "eu-west-2")
    email_from: str = os.getenv("SES_FROM_EMAIL", "")
    google_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    chat_model: str = os.getenv("BEDROCK_CHAT_MODEL_ID", "")
    embedding_model: str = os.getenv(
        "BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0"
    )
    mail_mode: str = os.getenv("MAIL_MODE", "ses")
    smtp_host: str = os.getenv("SMTP_HOST", "mailpit")
    smtp_port: int = int(os.getenv("SMTP_PORT", "1025"))


settings = Settings()
if len(settings.secret) < 32 or settings.secret.startswith("replace-with"):
    raise RuntimeError(
        "AUTH_SECRET must contain at least 32 random characters. See .env.example."
    )
if settings.environment == "production":
    if not settings.origin.startswith("https://") or settings.mail_mode != "ses":
        raise RuntimeError("Production requires HTTPS and SES email delivery")
    if not settings.database_url.startswith("postgresql"):
        raise RuntimeError("Production requires PostgreSQL")

if settings.idle_seconds < 60 or settings.max_sessions < 1:
    raise RuntimeError("Invalid session policy")
jwt_keys = (
    json.loads(settings.jwt_keys_json)
    if settings.jwt_keys_json
    else {settings.active_kid: settings.secret}
)
if not isinstance(jwt_keys, dict) or any(
    not isinstance(k, str) or not isinstance(v, str) or len(v) < 32
    for k, v in jwt_keys.items()
):
    raise RuntimeError(
        "JWT_SIGNING_KEYS must map key identifiers to 32+ character random keys"
    )
if settings.active_kid not in jwt_keys:
    raise RuntimeError("JWT_ACTIVE_KID is missing from JWT_SIGNING_KEYS")
if (
    settings.environment == "production"
    and settings.role == "api"
    and not settings.jwt_keys_json
):
    raise RuntimeError("Production API requires a separate JWT_SIGNING_KEYS secret")
