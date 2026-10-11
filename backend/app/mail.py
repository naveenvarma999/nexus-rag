import base64, hashlib, json, time
from cryptography.fernet import Fernet
from sqlalchemy import String, Text, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, uid
from .config import settings


class Outbox(Base):
    __tablename__ = "email_outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    payload: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0)
    claim_token: Mapped[str] = mapped_column(String(36), default="")
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    message_id: Mapped[str | None] = mapped_column(Text)


def cipher():
    return Fernet(
        base64.urlsafe_b64encode(
            hashlib.sha256(("mail:" + settings.secret).encode()).digest()
        )
    )


def enqueue(db, email, subject, text, deliver=True, ttl=86400):
    db.add(
        Outbox(
            payload=cipher()
            .encrypt(
                json.dumps(
                    {
                        "to": email,
                        "subject": subject,
                        "text": text,
                        "deliver": deliver,
                        "expires": time.time() + ttl,
                    }
                ).encode()
            )
            .decode()
        )
    )
