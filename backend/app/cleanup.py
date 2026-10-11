"""Run daily using an ECS task override or docker compose run --rm api python -m app.cleanup."""

import time
from sqlalchemy import delete, select, or_
from .db import (
    SessionLocal,
    Rate,
    TokenBucket,
    Access,
    Refresh,
    Challenge,
    OAuthState,
    LoginSession,
    Audit,
    Lease,
)
from .mail import Outbox


def run():
    now = time.time()
    with SessionLocal.begin() as db:
        db.execute(delete(TokenBucket).where(TokenBucket.expires < now))
        db.execute(delete(Rate).where(Rate.expires < now))
        expired_sessions = select(LoginSession.id).where(LoginSession.expires < now)
        db.execute(
            delete(Access).where(
                or_(Access.expires < now, Access.session_id.in_(expired_sessions))
            )
        )
        db.execute(delete(Refresh).where(Refresh.expires < now))
        db.execute(delete(LoginSession).where(LoginSession.expires < now))
        db.execute(delete(Challenge).where(Challenge.expires < now - 86400))
        db.execute(delete(OAuthState).where(OAuthState.expires < now))
        db.execute(delete(Audit).where(Audit.created < now - 90 * 86400))
        db.execute(delete(Lease).where(Lease.expires < now))
        db.execute(
            delete(Outbox).where(Outbox.state.in_(["accepted", "expired", "failed"]))
        )


if __name__ == "__main__":
    run()
