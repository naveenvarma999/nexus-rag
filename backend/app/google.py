import base64, hashlib, secrets, time, hmac
from urllib.parse import urlencode
import httpx, jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from .config import settings
from .db import SessionLocal, OAuthState, User
from .security import digest, issue, gate, audit

router = APIRouter(prefix="/api/auth/google")
keys = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", timeout=10)


@router.get("/start")
def start():
    if not settings.google_id or not settings.google_secret:
        raise HTTPException(503, "Google sign-in has not been configured.")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    with SessionLocal.begin() as db:
        db.add(
            OAuthState(
                digest=digest(state),
                nonce=nonce,
                verifier=verifier,
                expires=time.time() + 300,
            )
        )
    query = urlencode(
        {
            "client_id": settings.google_id,
            "redirect_uri": settings.origin + "/api/auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .decode()
            .rstrip("="),
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + query)
    response.set_cookie(
        "oauth_state",
        state,
        max_age=300,
        httponly=True,
        secure=settings.origin.startswith("https://"),
        samesite="lax",
        path="/api/auth/google",
    )
    return response


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = ""):
    if (
        not state
        or not code
        or not hmac.compare_digest(state, request.cookies.get("oauth_state", ""))
    ):
        raise HTTPException(400, "Invalid Google sign-in state. Start again.")
    with SessionLocal.begin() as db:
        saved = db.scalar(
            select(OAuthState)
            .where(OAuthState.digest == digest(state))
            .with_for_update()
        )
        if not saved or saved.expires < time.time():
            raise HTTPException(400, "Google sign-in expired. Start again.")
        nonce, verifier = saved.nonce, saved.verifier
        db.delete(saved)
    try:
        r = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_id,
                "client_secret": settings.google_secret,
                "redirect_uri": settings.origin + "/api/auth/google/callback",
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10,
        )
        r.raise_for_status()
        token = r.json()["id_token"]
        claims = jwt.decode(
            token,
            keys.get_signing_key_from_jwt(token).key,
            algorithms=["RS256"],
            audience=settings.google_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={
                "require": ["exp", "iat", "sub", "nonce", "email", "email_verified"]
            },
        )
        if (
            not hmac.compare_digest(claims["nonce"], nonce)
            or claims["email_verified"] is not True
            or claims.get("azp", settings.google_id) != settings.google_id
        ):
            raise ValueError()
    except (httpx.HTTPError, jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(400, "Google identity could not be verified. Try again.")
    email = claims["email"].strip().lower()
    response = RedirectResponse("/", status_code=303)
    with SessionLocal.begin() as db:
        gate(db, "login:" + digest(email))
        user = db.scalar(select(User).where(User.google_sub == claims["sub"]))
        if not user:
            if db.scalar(select(User).where(User.email == email)):
                raise HTTPException(
                    409,
                    "This email already has an account. Sign in using its password. Automatic account linking is disabled.",
                )
            user = User(
                email=email,
                name=claims.get("name", email)[:80],
                verified=True,
                google_sub=claims["sub"],
            )
            db.add(user)
            db.flush()
        issue(db, response, user, request=request)
        audit(db, user.email, "google_login")
    response.delete_cookie("oauth_state", path="/api/auth/google")
    return response
