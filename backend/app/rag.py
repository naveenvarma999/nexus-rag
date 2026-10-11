import hashlib, json, math, time
from contextlib import contextmanager
import boto3
from botocore.config import Config
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, func
from .config import settings
from .db import SessionLocal, Document, Chunk, History, Lease, user_transaction
from .security import current, rate, gate

router = APIRouter(prefix="/api")


from .providers import embed, generate


@contextmanager
def capacity(user_id):
    rate("rag:user:" + user_id, 20, 60)
    rate("rag:global", 100, 60)
    with SessionLocal.begin() as db:
        gate(db, "rag-capacity")
        db.execute(delete(Lease).where(Lease.expires < time.time()))
        total = db.scalar(select(func.count()).select_from(Lease))
        own = db.scalar(
            select(func.count()).select_from(Lease).where(Lease.user_id == user_id)
        )
        if total >= 12 or own >= 2:
            raise HTTPException(
                429,
                "The service is busy. Please retry shortly.",
                headers={"Retry-After": "10"},
            )
        lease = Lease(user_id=user_id, expires=time.time() + 900)
        db.add(lease)
        db.flush()
        lease_id = lease.id
    try:
        yield
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(Lease).where(Lease.id == lease_id))


class Ingest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=20, max_length=20000)


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


@router.get("/documents")
def documents(request: Request):
    user = current(request)
    with user_transaction(user.id) as db:
        return [
            {"id": d.id, "title": d.title, "created": d.created, "status": d.status}
            for d in db.scalars(
                select(Document)
                .where(Document.user_id == user.id)
                .order_by(Document.created.desc())
            )
        ]


@router.post("/documents", status_code=202)
def ingest(body: Ingest, request: Request):
    user = current(request)
    fingerprint = hashlib.sha256(body.text.encode()).hexdigest()
    if not body.title.strip() or not body.text.strip():
        raise HTTPException(400, "Enter a title and document text.")
    with capacity(user.id):
        # Reserve the per-user ingestion transaction; atomic dedup and quota across replicas.
        with user_transaction(user.id) as db:
            gate(db, "ingest:" + user.id)
            if db.scalar(
                select(Document).where(
                    Document.user_id == user.id, Document.content_hash == fingerprint
                )
            ):
                raise HTTPException(409, "This document has already been added.")
            if (
                db.scalar(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.user_id == user.id)
                )
                >= 100
            ):
                raise HTTPException(
                    409, "Your document limit is 100. Remove an older document first."
                )
            doc = Document(
                user_id=user.id,
                title=body.title.strip(),
                content_hash=fingerprint,
                content=body.text,
                status="pending",
            )
            db.add(doc)
            db.flush()
            return {"id": doc.id, "title": doc.title, "status": "pending"}


@router.delete("/documents/{document_id}")
def remove(document_id: str, request: Request):
    user = current(request)
    with user_transaction(user.id) as db:
        doc = db.scalar(
            select(Document).where(
                Document.id == document_id, Document.user_id == user.id
            )
        )
        if not doc:
            raise HTTPException(404, "Document not found.")
        db.execute(
            delete(Chunk).where(Chunk.document_id == doc.id, Chunk.user_id == user.id)
        )
        db.delete(doc)
    return {
        "message": "Document removed. Existing history is retained until you clear it."
    }


@router.post("/chat")
def chat(body: Question, request: Request):
    user = current(request)
    with capacity(user.id):
        vector = embed(body.question)
        with user_transaction(user.id) as db:
            query = (
                select(Chunk, Document.title)
                .join(Document, Document.id == Chunk.document_id)
                .where(
                    Chunk.user_id == user.id,
                    Document.user_id == user.id,
                    Document.status == "ready",
                )
            )
            if db.bind.dialect.name == "postgresql":
                rows = db.execute(
                    query.order_by(Chunk.embedding.cosine_distance(vector)).limit(5)
                ).all()
            else:

                def cosine(row):
                    a = row[0].embedding
                    return sum(x * y for x, y in zip(a, vector)) / (
                        math.sqrt(sum(x * x for x in a))
                        * math.sqrt(sum(x * x for x in vector))
                        or 1
                    )

                rows = sorted(db.execute(query).all(), key=cosine, reverse=True)[:5]
            sources = [
                {
                    "document_id": c.document_id,
                    "title": title,
                    "text": c.text,
                    "chunk": c.ordinal,
                }
                for c, title in rows
            ]
        if not sources:
            raise HTTPException(400, "Add a document before asking a question.")
        answer = generate(body.question, sources)
        with user_transaction(user.id) as db:
            item = History(
                user_id=user.id, question=body.question, answer=answer, sources=sources
            )
            db.add(item)
            db.flush()
            return {
                "id": item.id,
                "question": item.question,
                "answer": answer,
                "sources": sources,
                "created": item.created,
            }


@router.get("/history")
def history(request: Request):
    user = current(request)
    with user_transaction(user.id) as db:
        return [
            {
                "id": h.id,
                "question": h.question,
                "answer": h.answer,
                "sources": h.sources,
                "created": h.created,
            }
            for h in db.scalars(
                select(History)
                .where(History.user_id == user.id)
                .order_by(History.created.desc())
                .limit(100)
            )
        ]


@router.delete("/history")
def clear_history(request: Request):
    user = current(request)
    with user_transaction(user.id) as db:
        db.execute(delete(History).where(History.user_id == user.id))
    return {"message": "History cleared"}
