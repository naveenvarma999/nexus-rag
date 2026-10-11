import time, secrets, hmac, math
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from .db import SessionLocal, User, Challenge, LoginSession, Refresh
from .security import (
    digest,
    gate,
    audit,
    rate,
    password_hash,
    check_password,
    issue,
    revoke,
    require_csrf,
    clear_cookies,
    current,
    hasher,
)
from .mail import enqueue
from .config import settings

router = APIRouter(prefix="/api/auth")


class EmailInput(BaseModel):
    email: EmailStr


class Signup(EmailInput):
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=128)


class Verify(EmailInput):
    code: str = Field(pattern=r"^\d{6}$")


class Reset(Verify):
    password: str = Field(min_length=12, max_length=128)


class Login(EmailInput):
    password: str = Field(min_length=1, max_length=128)


def canonical(email):
    return str(email).strip().lower()


def budget(email, kind):
    rate("mail:global", 100, 3600)
    rate("mail:" + kind + ":" + digest(email), 3, 3600)
    rate("mail-cooldown:" + kind + ":" + digest(email), 1, 60)


def start_challenge(db, email, purpose, name=None, pwhash=None, deliver=True):
    gate(db, "otp:" + digest(email) + ":" + purpose)
    db.execute(
        update(Challenge)
        .where(
            Challenge.email == email,
            Challenge.purpose == purpose,
            Challenge.used == False,
        )
        .values(used=True)
    )
    code = f"{secrets.randbelow(1000000):06d}"
    row = Challenge(
        email=email,
        purpose=purpose,
        code_hash=digest(email + ":" + purpose + ":" + code),
        password_hash=pwhash,
        name=name,
        expires=time.time() + 600,
    )
    db.add(row)
    enqueue(
        db,
        email,
        "Nexus " + ("email verification" if purpose == "signup" else "password reset"),
        f"Your Nexus verification code is {code}. It expires in 10 minutes. Do not share this code. If you did not request it, ignore this message.",
        deliver,
        ttl=600,
    )


def consume(db, email, purpose, code):
    lock = gate(db, "otp:" + digest(email) + ":" + purpose)
    if lock.locked_until > time.time():
        return None, math.ceil(lock.locked_until - time.time())
    row = db.scalar(
        select(Challenge)
        .where(
            Challenge.email == email,
            Challenge.purpose == purpose,
            Challenge.used == False,
        )
        .order_by(Challenge.expires.desc())
        .with_for_update()
    )
    if not row or row.expires < time.time():
        return None, 0
    if not hmac.compare_digest(
        row.code_hash, digest(email + ":" + purpose + ":" + code)
    ):
        row.attempts += 1
        lock.failures += 1
        if lock.failures >= 5:
            lock.locked_until = time.time() + 3600
            lock.failures = 0
            row.used = True
            return None, 3600
        return None, 0
    row.used = True
    lock.failures = 0
    lock.locked_until = 0
    return row, 0


def invalid_code(retry):
    raise HTTPException(
        429 if retry else 400,
        (
            "Too many incorrect codes. Retry after one hour."
            if retry
            else "Invalid or expired code."
        ),
        headers={"Retry-After": str(retry)} if retry else None,
    )


@router.post("/signup")
def signup(body: Signup):
    if not body.name.strip():
        raise HTTPException(400, "Enter your name.")
    email = canonical(body.email)
    budget(email, "signup")
    pwhash = password_hash(body.password)
    with SessionLocal.begin() as db:
        lock = gate(db, "login:" + digest(email))
        existing = db.scalar(select(User).where(User.email == email))
        start_challenge(
            db, email, "signup", body.name.strip(), pwhash, deliver=not bool(existing)
        )
        audit(db, email, "signup_requested")
    return {
        "message": "If this address is eligible, a verification code will arrive shortly. Check your inbox."
    }


@router.post("/verify-email")
def verify_email(body: Verify):
    email = canonical(body.email)
    rate("verify:" + digest(email), 20, 3600)
    with SessionLocal.begin() as db:
        gate(db, "login:" + digest(email))
        row, retry = consume(db, email, "signup", body.code)
        if row:
            existing = db.scalar(select(User).where(User.email == email))
            if not existing:
                db.add(
                    User(
                        email=email,
                        name=row.name,
                        password_hash=row.password_hash,
                        verified=True,
                    )
                )
            audit(db, email, "email_verified")
    if not row:
        invalid_code(retry)
    return {"message": "Email verified. You can now sign in."}


@router.post("/login")
def login(body: Login, response: Response, request: Request):
    email = canonical(body.email)
    rate("login-requests:" + digest(email), 30, 3600)
    failure = None
    retry = 0
    user_data = None
    with SessionLocal.begin() as db:
        lock = gate(db, "login:" + digest(email))
        now = time.time()
        if lock.locked_until > now:
            failure = "Account temporarily locked. Retry after the lockout expires."
            retry = math.ceil(lock.locked_until - now)
        else:
            if lock.locked_until:
                lock.locked_until = 0
                lock.failures = 0
            user = db.scalar(select(User).where(User.email == email))
            valid = check_password(user.password_hash if user else None, body.password)
            if not valid or not user or not user.verified or not user.password_hash:
                lock.failures += 1
                failure = "Invalid email or password."
                if lock.failures >= 5:
                    lock.locked_until = now + 3600
                    retry = 3600
                    failure = "Five incorrect attempts. Sign-in is locked for one hour."
                audit(db, email, "login_failed")
            else:
                lock.failures = 0
                lock.locked_until = 0
                if hasher.check_needs_rehash(user.password_hash):
                    user.password_hash = password_hash(body.password)
                issue(db, response, user, request=request)
                audit(db, email, "login_success")
                user_data = {"id": user.id, "email": user.email, "name": user.name}
    if failure:
        raise HTTPException(
            429 if retry else 401,
            failure,
            headers={"Retry-After": str(retry)} if retry else None,
        )
    return {"user": user_data}


@router.post("/forgot-password")
def forgot(body: EmailInput):
    email = canonical(body.email)
    budget(email, "reset")
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == email, User.verified == True))
        start_challenge(db, email, "reset", deliver=bool(user and user.password_hash))
        audit(db, email, "reset_requested")
    return {
        "message": "If an eligible account exists, a reset code will arrive shortly."
    }


@router.post("/reset-password")
def reset(body: Reset):
    email = canonical(body.email)
    rate("reset-verify:" + digest(email), 20, 3600)
    pwhash = password_hash(body.password)
    with SessionLocal.begin() as db:
        login_lock = gate(db, "login:" + digest(email))
        row, retry = consume(db, email, "reset", body.code)
        user = db.scalar(select(User).where(User.email == email)) if row else None
        if user and user.password_hash:
            user.password_hash = pwhash
            login_lock.failures = 0
            login_lock.locked_until = 0
            for session in db.scalars(
                select(LoginSession)
                .where(LoginSession.user_id == user.id)
                .with_for_update()
            ):
                revoke(db, session)
            enqueue(
                db,
                email,
                "Your Nexus password changed",
                "Your password has been changed and all sessions have been signed out. If this was not you, contact your administrator immediately.",
            )
            audit(db, email, "password_reset")
        else:
            row = None
    if not row:
        invalid_code(retry)
    return {"message": "Password changed. Sign in with your new password."}


@router.post("/refresh")
def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token", "")
    rate("refresh:" + digest(token), 30, 60)
    failed = False
    with SessionLocal.begin() as db:
        ref = db.scalar(select(Refresh).where(Refresh.digest == digest(token)))
        session = (
            db.scalar(
                select(LoginSession)
                .where(LoginSession.id == ref.session_id)
                .with_for_update()
            )
            if ref
            else None
        )
        if (
            not ref
            or not session
            or session.revoked
            or session.expires < time.time()
            or session.last_seen + settings.idle_seconds < time.time()
            or ref.expires < time.time()
        ):
            failed = True
        else:
            require_csrf(request, session)
            db.refresh(ref)
            if ref.consumed:
                revoke(db, session)
                audit(db, db.get(User, session.user_id).email, "refresh_reuse")
                failed = True
            else:
                ref.consumed = True
                user = db.get(User, session.user_id)
                issue(db, response, user, session)
                audit(db, user.email, "refresh_rotated")
    if failed:
        raise HTTPException(401, "Session expired or revoked. Sign in again.")
    return {"message": "Session renewed"}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("refresh_token", "")
    with SessionLocal.begin() as db:
        ref = db.get(Refresh, digest(token))
        session = (
            db.scalar(
                select(LoginSession)
                .where(LoginSession.id == ref.session_id)
                .with_for_update()
            )
            if ref
            else None
        )
        if session:
            require_csrf(request, session)
            revoke(db, session)
            audit(db, db.get(User, session.user_id).email, "logout")
    clear_cookies(response)
    return {"message": "Signed out"}


@router.get("/me")
def me(request: Request):
    u = current(request)
    return {"user": {"id": u.id, "email": u.email, "name": u.name}}
