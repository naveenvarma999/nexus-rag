import time
import uuid
from sqlalchemy import (
    create_engine,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    JSON,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings
from pgvector.sqlalchemy import Vector

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    **(
        {"connect_args": {"check_same_thread": False}}
        if settings.database_url.startswith("sqlite")
        else {
            "pool_size": 5,
            "max_overflow": 5,
            "pool_timeout": 10,
            "connect_args": {
                "connect_timeout": 3,
                "options": "-c statement_timeout=5000 -c lock_timeout=2000",
            },
        }
    )
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Gate(Base):
    __tablename__ = "auth_gates"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[float] = mapped_column(Float, default=0)


class Rate(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(String(180), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires: Mapped[float] = mapped_column(Float, default=0)


class Challenge(Base):
    __tablename__ = "email_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(String(80))
    expires: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    last_seen: Mapped[float] = mapped_column(Float, default=time.time)
    user_agent: Mapped[str] = mapped_column(String(200), default="")
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Refresh(Base):
    __tablename__ = "refresh_tokens"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("login_sessions.id"), index=True)
    expires: Mapped[float] = mapped_column(Float)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Access(Base):
    __tablename__ = "access_tokens"
    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("login_sessions.id"), index=True)
    expires: Mapped[float] = mapped_column(Float)
    blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(50))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    claim_token: Mapped[str] = mapped_column(String(36), default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (Index("document_dedup", "user_id", "content_hash", unique=True),)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list] = mapped_column(Vector(1024).with_variant(JSON(), "sqlite"))


class History(Base):
    __tablename__ = "search_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(100))
    verifier: Mapped[str] = mapped_column(String(100))
    expires: Mapped[float] = mapped_column(Float)


class Lease(Base):
    __tablename__ = "work_leases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    expires: Mapped[float] = mapped_column(Float)


class TokenBucket(Base):
    __tablename__ = "token_buckets"
    key: Mapped[str] = mapped_column(String(180), primary_key=True)
    tokens: Mapped[float] = mapped_column(Float)
    updated: Mapped[float] = mapped_column(Float)
    expires: Mapped[float] = mapped_column(Float)


class Circuit(Base):
    __tablename__ = "provider_circuits"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    open_until: Mapped[float] = mapped_column(Float, default=0)
    probe_until: Mapped[float] = mapped_column(Float, default=0)
    generation: Mapped[int] = mapped_column(Integer, default=0)


from contextlib import contextmanager


@contextmanager
def user_transaction(user_id):
    """Transaction-local identity cannot leak through a reused pool connection."""
    with SessionLocal.begin() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user_id}
            )
        yield db
