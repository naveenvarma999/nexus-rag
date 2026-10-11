import os, tempfile, re, json, time

os.environ["AUTH_SECRET"] = "test-secret-" + "x" * 48
test_url = os.getenv("TEST_DATABASE_URL")
if test_url and "nexus_test" not in test_url:
    raise RuntimeError("Use an isolated database named nexus_test")
os.environ["DATABASE_URL"] = test_url or "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["APP_ORIGIN"] = "http://localhost:8000"
os.environ["MAIL_MODE"] = "smtp"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, delete, text
from app.main import app
from app.db import (
    Base,
    engine,
    SessionLocal,
    User,
    Gate,
    Rate,
    TokenBucket,
    Document,
    Chunk,
    History,
    LoginSession,
    Challenge,
)
from app.mail import Outbox, cipher
from app.security import password_hash, digest
from app import rag, indexer


@pytest.fixture(autouse=True)
def schema():
    if engine.dialect.name == "postgresql":
        with engine.begin() as db:
            db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(
        app,
        base_url="http://localhost:8000",
        headers={"origin": "http://localhost:8000"},
    ) as client:
        yield client


def code(email):
    with SessionLocal() as db:
        rows = db.scalars(select(Outbox)).all()
        for row in reversed(rows):
            payload = json.loads(cipher().decrypt(row.payload.encode()))
            if payload["to"] == email and "code is " in payload["text"]:
                return re.search(r"code is (\d{6})", payload["text"])[1]


def signup(client, email="alex@example.com"):
    assert (
        client.post(
            "/api/auth/signup",
            json={"name": "Alex", "email": email, "password": "a strong password!"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/verify-email", json={"email": email, "code": code(email)}
        ).status_code
        == 200
    )


def login(client, email="alex@example.com", password="a strong password!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.headers["x-csrf-token"] = client.cookies["csrf_token"]
    return r


def test_registration_verification_and_hash(client):
    data = {
        "name": "Alex",
        "email": "alex@example.com",
        "password": "a strong password!",
    }
    assert client.post("/api/auth/signup", json=data).status_code == 200
    assert client.post("/api/auth/login", json=data).status_code == 401
    otp = code(data["email"])
    assert (
        client.post(
            "/api/auth/verify-email", json={"email": data["email"], "code": otp}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/verify-email", json={"email": data["email"], "code": otp}
        ).status_code
        == 400
    )
    login(client)
    with SessionLocal() as db:
        user = db.scalar(select(User))
        assert user.verified and user.password_hash.startswith("$argon2id$")
    assert client.get("/api/auth/me").status_code == 200


def test_five_failures_lock_for_one_hour(client):
    signup(client)
    for _ in range(4):
        assert (
            client.post(
                "/api/auth/login",
                json={"email": "alex@example.com", "password": "wrong"},
            ).status_code
            == 401
        )
    r = client.post(
        "/api/auth/login", json={"email": "alex@example.com", "password": "wrong"}
    )
    assert r.status_code == 429 and r.headers["retry-after"] == "3600"
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "alex@example.com", "password": "a strong password!"},
        ).status_code
        == 429
    )
    with SessionLocal.begin() as db:
        db.get(Gate, "login:" + digest("alex@example.com")).locked_until = (
            time.time() - 1
        )
    login(client)


def test_bad_otp_lock_cannot_be_reset_by_resend(client):
    email = "alex@example.com"
    client.post(
        "/api/auth/signup",
        json={"name": "Alex", "email": email, "password": "a strong password!"},
    )
    correct = code(email)
    wrong = "000000" if correct != "000000" else "999999"
    for _ in range(4):
        assert (
            client.post(
                "/api/auth/verify-email", json={"email": email, "code": wrong}
            ).status_code
            == 400
        )
    assert (
        client.post(
            "/api/auth/verify-email", json={"email": email, "code": wrong}
        ).status_code
        == 429
    )
    with SessionLocal.begin() as db:
        db.execute(delete(Rate))
        db.execute(delete(TokenBucket))
    client.post(
        "/api/auth/signup",
        json={"name": "Alex", "email": email, "password": "a strong password!"},
    )
    assert (
        client.post(
            "/api/auth/verify-email", json={"email": email, "code": code(email)}
        ).status_code
        == 429
    )


def test_reset_revokes_sessions_and_code_is_single_use(client):
    signup(client)
    login(client)
    token = client.cookies["access_token"]
    assert (
        client.post(
            "/api/auth/forgot-password", json={"email": "alex@example.com"}
        ).status_code
        == 200
    )
    reset = {
        "email": "alex@example.com",
        "code": code("alex@example.com"),
        "password": "a different strong password!",
    }
    assert client.post("/api/auth/reset-password", json=reset).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/reset-password", json=reset).status_code == 400
    login(client, password=reset["password"])


def test_refresh_replay_revokes_entire_family(client):
    signup(client)
    login(client)
    old = client.cookies["refresh_token"]
    csrf = client.cookies["csrf_token"]
    assert client.post("/api/auth/refresh").status_code == 200
    assert client.cookies["refresh_token"] != old
    r = client.post(
        "/api/auth/refresh",
        headers={
            "cookie": f"refresh_token={old}; csrf_token={csrf}",
            "x-csrf-token": csrf,
        },
    )
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_logout_blacklists_copied_access_token(client):
    signup(client)
    login(client)
    token = client.cookies["access_token"]
    assert client.post("/api/auth/logout").status_code == 200
    assert (
        client.get(
            "/api/auth/me", headers={"cookie": f"access_token={token}"}
        ).status_code
        == 401
    )


def test_csrf_origin_and_size_rejection(client):
    signup(client)
    login(client)
    assert (
        client.post("/api/auth/logout", headers={"x-csrf-token": "wrong"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/logout", headers={"origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.post("/api/auth/login", content="x" * 131073).status_code == 413
    assert (
        client.get("/")
        .headers["content-security-policy"]
        .startswith("default-src 'self'")
    )


def test_expired_code_and_generic_reset_response(client):
    client.post(
        "/api/auth/signup",
        json={
            "email": "alex@example.com",
            "name": "Alex",
            "password": "a strong password!",
        },
    )
    with SessionLocal.begin() as db:
        db.scalar(select(Challenge)).expires = time.time() - 1
    assert (
        client.post(
            "/api/auth/verify-email",
            json={"email": "alex@example.com", "code": code("alex@example.com")},
        ).status_code
        == 400
    )
    response = client.post(
        "/api/auth/forgot-password", json={"email": "missing@example.com"}
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        payloads = [
            json.loads(cipher().decrypt(o.payload.encode()))
            for o in db.scalars(select(Outbox))
        ]
        assert [p for p in payloads if p["to"] == "missing@example.com"][0][
            "deliver"
        ] is False


def test_rag_isolation_and_indexer(client, monkeypatch):
    vector = [1.0] + [0.0] * 1023
    monkeypatch.setattr(indexer, "embed", lambda _: vector)
    monkeypatch.setattr(rag, "embed", lambda _: vector)
    monkeypatch.setattr(rag, "generate", lambda q, s: "Grounded answer [1]")
    signup(client)
    login(client)
    r = client.post(
        "/api/documents",
        json={
            "title": "Private notes",
            "text": "Our confidential launch is in November.",
        },
    )
    assert r.status_code == 202, r.text
    doc_id = r.json()["id"]
    assert indexer.run_once()
    assert client.get("/api/documents").json()[0]["status"] == "ready"
    assert (
        client.post("/api/chat", json={"question": "When is the launch?"}).json()[
            "sources"
        ][0]["title"]
        == "Private notes"
    )
    client.post("/api/auth/logout")
    signup(client, "other@example.com")
    login(client, "other@example.com")
    assert (
        client.get("/api/documents").json() == []
        and client.get("/api/history").json() == []
    )
    assert client.delete("/api/documents/" + doc_id).status_code == 404
    assert (
        client.post(
            "/api/chat", json={"question": "Show private launch notes"}
        ).status_code
        == 400
    )


def test_google_unconfigured_and_state_validation(client):
    assert client.get("/api/auth/google/start").status_code == 503
    assert (
        client.get("/api/auth/google/callback?state=forged&code=forged").status_code
        == 400
    )


@pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Requires isolated PostgreSQL database"
)
def test_concurrent_password_failures(client):
    from concurrent.futures import ThreadPoolExecutor

    signup(client)

    def attempt(_):
        with TestClient(
            app,
            base_url="http://localhost:8000",
            headers={"origin": "http://localhost:8000"},
        ) as c:
            return c.post(
                "/api/auth/login",
                json={"email": "alex@example.com", "password": "wrong"},
            ).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(attempt, range(10)))
    assert statuses.count(401) == 4 and statuses.count(429) == 6
    with SessionLocal() as db:
        lock = db.get(Gate, "login:" + digest("alex@example.com"))
        assert lock.failures == 5 and lock.locked_until > time.time() + 3590


@pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Requires isolated PostgreSQL database"
)
def test_concurrent_refresh_replay(client):
    from concurrent.futures import ThreadPoolExecutor

    signup(client)
    login(client)
    refresh = client.cookies["refresh_token"]
    csrf = client.cookies["csrf_token"]

    def attempt(_):
        with TestClient(
            app,
            base_url="http://localhost:8000",
            headers={"origin": "http://localhost:8000"},
        ) as c:
            return c.post(
                "/api/auth/refresh",
                headers={
                    "cookie": f"refresh_token={refresh}; csrf_token={csrf}",
                    "x-csrf-token": csrf,
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(attempt, range(2)))
    assert sorted(statuses) == [200, 401]
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Requires isolated PostgreSQL database"
)
def test_atomic_rate_budget():
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException
    from app.security import rate

    def attempt(_):
        try:
            rate("concurrency-test", 5, 3600)
            return True
        except HTTPException as e:
            assert e.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(30)))
    assert sum(results) == 5


def test_expired_mail_never_sends(client, monkeypatch):
    from app import worker
    from app.mail import enqueue

    with SessionLocal.begin() as db:
        enqueue(db, "alex@example.com", "Expired code", "code is 123456", ttl=-1)

    def forbidden(*args, **kwargs):
        raise AssertionError("Expired email must not be sent")

    monkeypatch.setattr(worker.smtplib, "SMTP", forbidden)
    assert worker.run_once()
    with SessionLocal() as db:
        row = db.scalar(select(Outbox))
        assert row.state == "expired" and row.payload == ""


def test_google_signed_identity_and_one_use_state(client, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from urllib.parse import urlparse, parse_qs
    from cryptography.hazmat.primitives.asymmetric import rsa
    import jwt
    from app import google
    from app.db import OAuthState

    monkeypatch.setattr(
        google,
        "settings",
        replace(google.settings, google_id="test-client", google_secret="test-secret"),
    )
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        google,
        "keys",
        SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key())
        ),
    )
    start = client.get("/api/auth/google/start", follow_redirects=False)
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    token = jwt.encode(
        {
            "sub": "google-test-identity",
            "email": "google@example.com",
            "email_verified": True,
            "name": "Google Tester",
            "nonce": query["nonce"][0],
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "iss": "https://accounts.google.com",
            "aud": "test-client",
        },
        private,
        algorithm="RS256",
    )
    monkeypatch.setattr(
        google.httpx,
        "post",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"id_token": token}
        ),
    )
    url = "/api/auth/google/callback?code=provider-code&state=" + query["state"][0]
    result = client.get(url, follow_redirects=False)
    assert result.status_code == 303, result.text
    assert client.get("/api/auth/me").json()["user"]["email"] == "google@example.com"
    assert client.get(url, follow_redirects=False).status_code == 400


def test_tampered_jwt_is_rejected(client):
    import jwt
    from app.config import settings

    signup(client)
    login(client)
    token = client.cookies["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["aud"] = "another-service"
    forged = jwt.encode(
        claims, settings.secret, algorithm="HS256", headers={"kid": settings.active_kid}
    )
    assert (
        client.get(
            "/api/auth/me", headers={"cookie": "access_token=" + forged}
        ).status_code
        == 401
    )


def test_worker_smtp_acceptance_erases_payload(client, monkeypatch):
    from app import worker
    from app.mail import enqueue

    sent = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(worker.smtplib, "SMTP", SMTP)
    with SessionLocal.begin() as db:
        enqueue(db, "alex@example.com", "Test", "Verification code is 123456")
    assert worker.run_once() and len(sent) == 1
    with SessionLocal() as db:
        row = db.scalar(select(Outbox))
        assert row.state == "accepted" and row.payload == ""


def test_idle_session_cannot_be_refreshed(client):
    signup(client)
    login(client)
    from app.config import settings

    with SessionLocal.begin() as db:
        db.scalar(select(LoginSession)).last_seen = (
            time.time() - settings.idle_seconds - 1
        )
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/refresh").status_code == 401


def test_session_cap_and_remote_revocation(client):
    from app.config import settings

    signup(client)
    for _ in range(settings.max_sessions + 1):
        login(client)
    rows = client.get("/api/account/sessions").json()
    assert len(rows) == settings.max_sessions and sum(s["current"] for s in rows) == 1
    target = next(s["id"] for s in rows if not s["current"])
    assert client.delete("/api/account/sessions/" + target).status_code == 200
    assert len(client.get("/api/account/sessions").json()) == settings.max_sessions - 1
    assert client.post("/api/account/logout-all").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_change_password_requires_current_and_revokes(client):
    signup(client)
    login(client)
    assert (
        client.post(
            "/api/account/password",
            json={
                "current_password": "incorrect",
                "new_password": "a new secure password!",
            },
        ).status_code
        == 400
    )
    assert client.get("/api/auth/me").status_code == 200
    assert (
        client.post(
            "/api/account/password",
            json={
                "current_password": "a strong password!",
                "new_password": "a new secure password!",
            },
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me").status_code == 401
    login(client, password="a new secure password!")


def test_key_rotation_overlap_and_unknown_key(client, monkeypatch):
    import jwt
    from app import security

    signup(client)
    login(client)
    token = client.cookies["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    monkeypatch.setitem(security.jwt_keys, "old-key", "z" * 48)
    old = jwt.encode(claims, "z" * 48, algorithm="HS256", headers={"kid": "old-key"})
    assert (
        client.get(
            "/api/auth/me", headers={"cookie": "access_token=" + old}
        ).status_code
        == 200
    )
    monkeypatch.delitem(security.jwt_keys, "old-key")
    assert (
        client.get(
            "/api/auth/me", headers={"cookie": "access_token=" + old}
        ).status_code
        == 401
    )


def test_token_bucket_has_no_window_boundary_reset(monkeypatch):
    from app.security import rate
    from fastapi import HTTPException

    clock = [119.0]
    if engine.dialect.name != "postgresql":
        monkeypatch.setattr(time, "time", lambda: clock[0])
    for _ in range(3):
        rate("boundary", 3, 60)
    clock[0] = 121.0
    if engine.dialect.name == "postgresql":
        with SessionLocal.begin() as db:
            db.get(TokenBucket, "boundary").updated -= 2
    with pytest.raises(HTTPException) as e:
        rate("boundary", 3, 60)
    assert e.value.status_code == 429
    clock[0] = 140.0
    if engine.dialect.name == "postgresql":
        with SessionLocal.begin() as db:
            db.get(TokenBucket, "boundary").updated -= 19
    rate("boundary", 3, 60)
    with pytest.raises(HTTPException):
        rate("boundary", 3, 60)


def test_worker_retries_then_dead_letters(client, monkeypatch):
    signup(client)
    login(client)
    doc_id = client.post(
        "/api/documents",
        json={
            "title": "Retry test",
            "text": "This document should reach the dead letter state.",
        },
    ).json()["id"]

    def fail(_):
        raise RuntimeError("Provider unavailable")

    monkeypatch.setattr(indexer, "embed", fail)
    for attempt in range(5):
        with SessionLocal.begin() as db:
            db.get(Document, doc_id).next_attempt = 0
        assert indexer.run_once()
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "failed" and doc.attempts == 5 and doc.content == ""
        assert db.scalars(select(Chunk)).all() == []


def test_worker_fencing_prevents_stale_publish(client):
    signup(client)
    login(client)
    doc_id = client.post(
        "/api/documents",
        json={
            "title": "Fence",
            "text": "A stale worker must never publish these chunks.",
        },
    ).json()["id"]
    old = indexer.claim()
    with SessionLocal.begin() as db:
        db.get(Document, doc_id).lease_until = time.time() - 1
    new = indexer.claim()
    assert old["claim"] != new["claim"]
    assert not indexer.finish(old, [("old data", [1.0] + [0.0] * 1023)])
    assert indexer.finish(new, [("new data", [1.0] + [0.0] * 1023)])
    with SessionLocal() as db:
        assert [c.text for c in db.scalars(select(Chunk))] == ["new data"]


def test_provider_breaker_recovers_one_probe(monkeypatch):
    from app.providers import breaker
    from botocore.exceptions import EndpointConnectionError
    from fastapi import HTTPException
    from app.db import Circuit

    for _ in range(5):
        with pytest.raises(EndpointConnectionError):
            with breaker("test"):
                raise EndpointConnectionError(endpoint_url="https://example.invalid")
    with pytest.raises(HTTPException):
        with breaker("test"):
            pass
    with SessionLocal.begin() as db:
        db.get(Circuit, "test").open_until = time.time() - 1
    with breaker("test"):
        with pytest.raises(HTTPException):
            with breaker("test"):
                pass
    with breaker("test"):
        pass
    with SessionLocal() as db:
        assert db.get(Circuit, "test").failures == 0


def test_security_headers_and_request_id(client):
    response = client.get("/health")
    import uuid

    uuid.UUID(response.headers["x-request-id"])
    assert "camera=()" in response.headers["permissions-policy"]


@pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Requires isolated PostgreSQL database"
)
def test_rls_denies_missing_and_wrong_identity(client):
    from app.migrate import install_rls

    signup(client)
    login(client)
    client.post(
        "/api/documents",
        json={
            "title": "RLS source",
            "text": "Private content enforced by the database policy.",
        },
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='nexus_rls_test') THEN CREATE ROLE nexus_rls_test NOSUPERUSER NOBYPASSRLS; END IF; END $$"
            )
        )
        conn.execute(text("GRANT USAGE ON SCHEMA public TO nexus_rls_test"))
        conn.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON documents TO nexus_rls_test")
        )
        install_rls(conn)
        user = conn.execute(text("SELECT id FROM users LIMIT 1")).scalar()
        conn.execute(text("SET LOCAL ROLE nexus_rls_test"))
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar() == 0
        conn.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": "wrong-user"}
        )
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar() == 0
        conn.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user}
        )
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar() == 1
    # A pooled connection must not retain the previous transaction's identity.
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE nexus_rls_test"))
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar() == 0


def test_forward_migration_adds_columns_and_runs_once(monkeypatch):
    from sqlalchemy import create_engine, inspect
    from app import migrate

    isolated = create_engine("sqlite://")
    with isolated.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE login_sessions (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), csrf_hash VARCHAR(64), expires FLOAT, revoked BOOLEAN, created FLOAT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO login_sessions VALUES ('legacy','owner','digest',99999999999,false,1)"
            )
        )
    monkeypatch.setattr(migrate, "engine", isolated)
    migrate.migrate()
    assert {"last_seen", "user_agent"} <= {
        c["name"] for c in inspect(isolated).get_columns("login_sessions")
    }
    with isolated.begin() as conn:
        assert (
            conn.execute(
                text("SELECT revoked FROM login_sessions WHERE id='legacy'")
            ).scalar()
            == 1
        )
        conn.execute(text("UPDATE login_sessions SET revoked=false WHERE id='legacy'"))
    migrate.migrate()
    with isolated.begin() as conn:
        assert (
            conn.execute(
                text("SELECT revoked FROM login_sessions WHERE id='legacy'")
            ).scalar()
            == 0
        )
    isolated.dispose()


@pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Requires isolated PostgreSQL database"
)
def test_worker_database_role_cannot_read_accounts(monkeypatch):
    from app.migrate import provision_role, install_rls
    from sqlalchemy.exc import ProgrammingError

    monkeypatch.setenv("TEST_INDEX_USER", "nexus_indexer_test")
    monkeypatch.setenv("TEST_INDEX_PASSWORD", "test-only-" + "x" * 40)
    with engine.begin() as conn:
        role = provision_role(
            conn,
            "TEST_INDEX",
            "nexus_indexer",
            ["documents", "chunks", "provider_circuits"],
        )
        install_rls(conn, role)
        conn.execute(text("SET LOCAL ROLE nexus_indexer_test"))
        conn.execute(text("SELECT count(*) FROM documents"))
        with pytest.raises(ProgrammingError):
            with conn.begin_nested():
                conn.execute(text("SELECT email FROM users"))
