"""Claim/execute/commit worker. External calls never hold a database transaction."""

import logging, time, secrets
from sqlalchemy import select, update, or_, and_
from .db import SessionLocal, Document, Chunk, uid
from .providers import embed

MAX_ATTEMPTS = 5
LEASE_SECONDS = 300


def claim():
    now = time.time()
    with SessionLocal.begin() as db:
        row = db.scalar(
            select(Document)
            .where(
                or_(
                    and_(Document.status == "pending", Document.next_attempt <= now),
                    and_(Document.status == "processing", Document.lease_until < now),
                )
            )
            .order_by(Document.created)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            return None
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            row.content = ""
            row.claim_token = ""
            return None
        row.status = "processing"
        row.attempts += 1
        row.claim_token = uid()
        row.lease_until = now + LEASE_SECONDS
        return {
            "id": row.id,
            "user_id": row.user_id,
            "content": row.content,
            "claim": row.claim_token,
            "attempts": row.attempts,
        }


def heartbeat(job):
    with SessionLocal.begin() as db:
        result = db.execute(
            update(Document)
            .where(
                Document.id == job["id"],
                Document.claim_token == job["claim"],
                Document.status == "processing",
            )
            .values(lease_until=time.time() + LEASE_SECONDS)
        )
        return result.rowcount == 1


def finish(job, chunks=None):
    with SessionLocal.begin() as db:
        row = db.scalar(
            select(Document)
            .where(
                Document.id == job["id"],
                Document.claim_token == job["claim"],
                Document.status == "processing",
            )
            .with_for_update()
        )
        if not row:
            return False  # A stale worker cannot publish after takeover/deletion.
        if chunks is not None:
            for i, (text, vector) in enumerate(chunks):
                db.add(
                    Chunk(
                        document_id=row.id,
                        user_id=row.user_id,
                        text=text,
                        ordinal=i,
                        embedding=vector,
                    )
                )
            row.status = "ready"
            row.content = ""
        elif row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            row.content = ""
        else:
            row.status = "pending"
            row.next_attempt = (
                time.time() + min(300, 2**row.attempts * 5) + secrets.randbelow(10)
            )
        row.claim_token = ""
        row.lease_until = 0
        return True


def run_once():
    job = claim()
    if not job:
        return False
    chunks = []
    try:
        for start in range(0, len(job["content"]), 1000):
            if not heartbeat(job):
                return True
            text = job["content"][start : start + 1200]
            chunks.append((text, embed(text)))
        finish(job, chunks)
    except Exception as exc:
        finish(job)
        logging.error(
            "index_failed document=%s attempt=%s error=%s",
            job["id"],
            job["attempts"],
            type(exc).__name__,
        )
    return True


if __name__ == "__main__":
    while True:
        try:
            if not run_once():
                time.sleep(2)
        except Exception as exc:
            logging.error("index_worker_unavailable error=%s", type(exc).__name__)
            time.sleep(5)
