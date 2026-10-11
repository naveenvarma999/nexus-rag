"""Account security operations; no administrative access to other users."""

import time, math
from fastapi import APIRouter, Request, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from .db import SessionLocal, LoginSession, User
from .security import (
    current,
    revoke,
    audit,
    gate,
    digest,
    rate,
    check_password,
    password_hash,
    clear_cookies,
)
from .mail import enqueue

router = APIRouter(prefix="/api/account")


@router.get("/sessions")
def sessions(request: Request):
    user = current(request)
    with SessionLocal() as db:
        return [
            {
                "id": s.id,
                "created": s.created,
                "last_seen": s.last_seen,
                "expires": s.expires,
                "device": s.user_agent or "Unknown browser",
                "current": s.id == request.state.session_id,
            }
            for s in db.scalars(
                select(LoginSession)
                .where(
                    LoginSession.user_id == user.id,
                    LoginSession.revoked == False,
                    LoginSession.expires > time.time(),
                )
                .order_by(LoginSession.created.desc())
            )
        ]


@router.delete("/sessions/{session_id}")
def remove_session(session_id: str, request: Request, response: Response):
    user = current(request)
    with SessionLocal.begin() as db:
        session = db.scalar(
            select(LoginSession)
            .where(LoginSession.id == session_id, LoginSession.user_id == user.id)
            .with_for_update()
        )
        if not session:
            raise HTTPException(404, "Session not found.")
        revoke(db, session)
        audit(db, user.email, "session_revoked")
    if session_id == request.state.session_id:
        clear_cookies(response)
    return {"message": "Session revoked"}


@router.post("/logout-all")
def logout_all(request: Request, response: Response):
    user = current(request)
    with SessionLocal.begin() as db:
        gate(db, "login:" + digest(user.email))
        for s in db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user.id)
            .order_by(LoginSession.id)
            .with_for_update()
        ):
            revoke(db, s)
        audit(db, user.email, "logout_all")
    clear_cookies(response)
    return {"message": "All sessions signed out"}


class ChangePassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/password")
def change_password(body: ChangePassword, request: Request, response: Response):
    actor = current(request)
    rate("password-change:" + actor.id, 10, 3600)
    failure = None
    retry = 0
    with SessionLocal.begin() as db:
        lock = gate(db, "login:" + digest(actor.email))
        user = db.get(User, actor.id)
        if lock.locked_until and lock.locked_until <= time.time():
            lock.locked_until = 0
            lock.failures = 0
        if lock.locked_until > time.time():
            retry = math.ceil(lock.locked_until - time.time())
            failure = "Password verification is temporarily locked."
        elif not user.password_hash:
            failure = "Manage your password through your Google account."
        elif not check_password(user.password_hash, body.current_password):
            lock.failures += 1
            failure = "Current password is incorrect."
            if lock.failures >= 5:
                lock.locked_until = time.time() + 3600
                retry = 3600
            audit(db, user.email, "password_change_failed")
        else:
            user.password_hash = password_hash(body.new_password)
            lock.failures = 0
            lock.locked_until = 0
            for s in db.scalars(
                select(LoginSession)
                .where(LoginSession.user_id == user.id)
                .order_by(LoginSession.id)
                .with_for_update()
            ):
                revoke(db, s)
            enqueue(
                db,
                user.email,
                "Your Nexus password changed",
                "Your password changed and all sessions were signed out. If this was not you, recover your account and contact your administrator.",
            )
            audit(db, user.email, "password_changed")
    if failure:
        raise HTTPException(
            429 if retry else 400,
            failure,
            headers={"Retry-After": str(retry)} if retry else None,
        )
    clear_cookies(response)
    return {"message": "Password changed. Please sign in again."}
