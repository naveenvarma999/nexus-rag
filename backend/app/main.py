import logging, os, time, uuid, json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from .config import settings
from .db import engine
from .security import rate, digest
from . import auth, google, rag, account

logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI(
    title="Nexus API",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url=None,
)


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # Buffer at most 128 KiB, including chunked transfer requests.
        size = 0
        messages = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 131072:
                return await JSONResponse(
                    {"detail": "Request too large."}, status_code=413
                )(scope, receive, send)
            messages.append(message)
            if not message.get("more_body"):
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)


app.add_middleware(BodyLimit)


@app.middleware("http")
async def gateway(request: Request, call_next):
    started = time.monotonic()
    request_id = str(uuid.uuid4())
    try:
        if request.url.path.startswith("/api/"):
            if (
                request.method not in ("GET", "HEAD", "OPTIONS")
                and request.headers.get("origin") != settings.origin
            ):
                raise HTTPException(403, "Request origin is not allowed.")
            # The edge must overwrite forwarding headers; this app trusts only its socket peer.
            peer = (
                request.headers.get("x-nexus-client-ip", "unknown")
                if settings.trust_gateway
                else (request.client.host if request.client else "unknown")
            )
            await run_in_threadpool(rate, "edge:" + digest(peer), 300, 60)
        response = await call_next(request)
    except HTTPException as exc:
        response = JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )
    except SQLAlchemyError:
        response = JSONResponse(
            {"detail": "The service is temporarily unavailable."}, status_code=503
        )
    response.headers["X-Request-ID"] = request_id
    # Route templates avoid document IDs, email addresses and query strings in logs.
    route = getattr(request.scope.get("route"), "path", "unmatched")
    logging.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "route": route,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
    )
    response.headers.update(
        {
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            "Cache-Control": "no-store",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
    )
    if settings.origin.startswith("https://"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    logging.error("Database operation failed: %s", type(exc).__name__)
    return JSONResponse(
        {"detail": "The service is temporarily unavailable. Please retry."},
        status_code=503,
    )


@app.exception_handler(BotoCoreError)
@app.exception_handler(ClientError)
async def provider_error(request, exc):
    logging.error("AWS operation failed: %s", type(exc).__name__)
    return JSONResponse(
        {
            "detail": "The AI provider is unavailable or not configured. Please contact your administrator."
        },
        status_code=503,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    with engine.connect() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/api/config")
def config():
    return {
        "google_enabled": bool(settings.google_id and settings.google_secret),
        "ai_configured": bool(settings.chat_model),
    }


app.include_router(account.router)
app.include_router(auth.router)
app.include_router(google.router)
app.include_router(rag.router)
frontend = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))
app.mount("/assets", StaticFiles(directory=frontend), name="assets")


@app.get("/")
def index():
    return FileResponse(os.path.join(frontend, "index.html"))
