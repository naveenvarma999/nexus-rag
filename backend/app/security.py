import hashlib, hmac, secrets, time, math
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException, Request, Response
from sqlalchemy import select, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .config import settings, jwt_keys
from .db import (
    SessionLocal,
    Gate,
    Rate,
    User,
    LoginSession,
    Refresh,
    Access,
    Audit,
    uid,
    TokenBucket,
)

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY = hasher.hash(secrets.token_urlsafe(32))


def digest(value):
    return hmac.new(
        settings.secret.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def password_hash(value):
    if not 12 <= len(value) <= 128:
        raise HTTPException(400, "Use a password of 12–128 characters.")
    return hasher.hash(value)


def check_password(encoded, value):
    try:
        return hasher.verify(encoded or DUMMY, value)
    except (VerificationError, InvalidHashError):
        return False


def insert_for(db, model):
    return (
        sqlite_insert(model) if db.bind.dialect.name == "sqlite" else pg_insert(model)
    )


def gate(db, key):
    db.execute(
        insert_for(db, Gate)
        .values(key=key, failures=0, locked_until=0)
        .on_conflict_do_nothing()
    )
    return db.scalar(select(Gate).where(Gate.key == key).with_for_update())


def audit(db, email, event):
    db.add(Audit(subject_hash=digest(email), event=event))


def rate(key, limit, seconds):
    """Shared token bucket: DB time, row locking, bounded burst and continuous refill."""
    retry = 0
    with SessionLocal.begin() as db:
        now = (
            float(db.scalar(text("SELECT EXTRACT(EPOCH FROM clock_timestamp())")))
            if db.bind.dialect.name == "postgresql"
            else time.time()
        )
        db.execute(
            insert_for(db, TokenBucket)
            .values(
                key=key, tokens=float(limit), updated=now, expires=now + seconds * 2
            )
            .on_conflict_do_nothing()
        )
        row = db.scalar(
            select(TokenBucket).where(TokenBucket.key == key).with_for_update()
        )
        # Obtain time after waiting on the lock; no application-host clock skew in PostgreSQL.
        if db.bind.dialect.name == "postgresql":
            now = float(db.scalar(text("SELECT EXTRACT(EPOCH FROM clock_timestamp())")))
        available = min(
            float(limit), row.tokens + max(0, now - row.updated) * limit / seconds
        )
        if available < 1:
            retry = max(1, math.ceil((1 - available) * seconds / limit))
        else:
            available -= 1
        row.tokens = available
        row.updated = now
        row.expires = now + seconds * 2
    if retry:
        raise HTTPException(
            429,
            "Too many requests. Try again later.",
            headers={"Retry-After": str(retry)},
        )


def require_csrf(request, session):
    if not hmac.compare_digest(
        digest(request.headers.get("x-csrf-token", "")), session.csrf_hash
    ):
        raise HTTPException(403, "Invalid CSRF token.")


def revoke(db, session):
    session.revoked = True
    db.execute(
        update(Access).where(Access.session_id == session.id).values(blacklisted=True)
    )


def issue(db, response, user, session=None, csrf=None, request=None):
    now = time.time()
    if session is None:
        # All new-session paths hold this user lock, so the cap works across replicas.
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        active = list(
            db.scalars(
                select(LoginSession)
                .where(
                    LoginSession.user_id == user.id,
                    LoginSession.revoked == False,
                    LoginSession.expires > now,
                )
                .order_by(LoginSession.created)
                .with_for_update()
            )
        )
        while len(active) >= settings.max_sessions:
            revoke(db, active.pop(0))
        csrf = secrets.token_urlsafe(32)
        session = LoginSession(
            user_id=user.id,
            last_seen=now,
            user_agent=(request.headers.get("user-agent", "")[:200] if request else ""),
            csrf_hash=digest(csrf),
            expires=now + 30 * 86400,
        )
        db.add(session)
        db.flush()
    session.last_seen = now
    refresh = secrets.token_urlsafe(48)
    jti = uid()
    exp = int(now) + 900
    db.add(
        Refresh(digest=digest(refresh), session_id=session.id, expires=session.expires)
    )
    db.add(Access(jti=jti, session_id=session.id, expires=exp))
    token = jwt.encode(
        {
            "sub": user.id,
            "sid": session.id,
            "jti": jti,
            "iat": int(now),
            "exp": exp,
            "iss": settings.origin,
            "aud": "nexus-api",
            "typ": "access",
        },
        jwt_keys[settings.active_kid],
        algorithm="HS256",
        headers={"kid": settings.active_kid},
    )
    secure = settings.origin.startswith("https://")
    response.set_cookie(
        "access_token",
        token,
        max_age=900,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "refresh_token",
        refresh,
        max_age=max(0, int(session.expires - now)),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api/auth",
    )
    if csrf:
        response.set_cookie(
            "csrf_token",
            csrf,
            max_age=30 * 86400,
            secure=secure,
            samesite="lax",
            path="/",
        )


def clear_cookies(response):
    for name, path in [
        ("access_token", "/"),
        ("refresh_token", "/api/auth"),
        ("csrf_token", "/"),
    ]:
        response.delete_cookie(
            name,
            path=path,
            secure=settings.origin.startswith("https://"),
            httponly=name != "csrf_token",
            samesite="lax",
        )


def current(request: Request):
    try:
        raw_token = request.cookies.get("access_token", "")
        kid = jwt.get_unverified_header(raw_token).get("kid")
        if kid not in jwt_keys:
            raise ValueError()
        claims = jwt.decode(
            request.cookies.get("access_token", ""),
            jwt_keys[kid],
            algorithms=["HS256"],
            issuer=settings.origin,
            audience="nexus-api",
            options={"require": ["exp", "iat", "sub", "sid", "jti"]},
        )
        if claims.get("typ") != "access":
            raise ValueError()
        with SessionLocal.begin() as db:
            session = db.get(LoginSession, claims["sid"])
            access = db.get(Access, claims["jti"])
            if (
                not session
                or session.revoked
                or session.expires < time.time()
                or session.last_seen + settings.idle_seconds < time.time()
                or not access
                or access.blacklisted
                or access.session_id != session.id
                or session.user_id != claims["sub"]
            ):
                raise ValueError()
            if request.method not in ("GET", "HEAD"):
                require_csrf(request, session)
            user = db.get(User, session.user_id)
            if not user or not user.verified:
                raise ValueError()
            # Conditional UPDATE avoids overwriting a concurrent revocation.
            touched = db.execute(
                update(LoginSession)
                .where(LoginSession.id == session.id, LoginSession.revoked == False)
                .values(last_seen=time.time())
            )
            if touched.rowcount != 1:
                raise ValueError()
            request.state.session_id = session.id
            return user
    except HTTPException:
        raise
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(401, "Please sign in.")
