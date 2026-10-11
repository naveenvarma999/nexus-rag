"""At-least-once outbox worker with short claim/commit transactions and fencing."""

import time, json, smtplib, logging
from email.message import EmailMessage
import boto3
from botocore.config import Config
from sqlalchemy import select, or_, and_
from .config import settings
from .db import SessionLocal, uid
from .mail import Outbox, cipher


def run_once():
    now = time.time()
    with SessionLocal.begin() as db:
        row = db.scalar(
            select(Outbox)
            .where(
                or_(
                    and_(Outbox.state == "pending", Outbox.next_attempt <= now),
                    and_(Outbox.state == "processing", Outbox.lease_until < now),
                )
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            return False
        if row.attempts >= 5:
            row.state = "failed"
            row.payload = ""
            return True
        row.state = "processing"
        row.attempts += 1
        row.claim_token = uid()
        row.lease_until = now + 60
        job = {"id": row.id, "claim": row.claim_token, "payload": row.payload}
    message_id = None
    state = "accepted"
    try:
        data = json.loads(cipher().decrypt(job["payload"].encode()))
        if data.get("expires", 0) < time.time():
            state = "expired"
        elif data["deliver"]:
            if settings.mail_mode == "smtp" and settings.environment != "production":
                msg = EmailMessage()
                msg["From"] = "nexus@localhost"
                msg["To"] = data["to"]
                msg["Subject"] = data["subject"]
                msg.set_content(data["text"])
                with smtplib.SMTP(
                    settings.smtp_host, settings.smtp_port, timeout=5
                ) as smtp:
                    smtp.send_message(msg)
                message_id = "development-smtp"
            else:
                if not settings.email_from:
                    raise RuntimeError("SES_FROM_EMAIL is not configured")
                result = boto3.client(
                    "sesv2",
                    region_name=settings.region,
                    config=Config(
                        connect_timeout=2,
                        read_timeout=5,
                        retries={"total_max_attempts": 1},
                    ),
                ).send_email(
                    FromEmailAddress=settings.email_from,
                    Destination={"ToAddresses": [data["to"]]},
                    Content={
                        "Simple": {
                            "Subject": {"Data": data["subject"]},
                            "Body": {"Text": {"Data": data["text"]}},
                        }
                    },
                )
                message_id = result["MessageId"]
    except Exception as exc:
        state = "pending"
        logging.error("email_failed job=%s error=%s", job["id"], type(exc).__name__)
    with SessionLocal.begin() as db:
        row = db.scalar(
            select(Outbox)
            .where(Outbox.id == job["id"], Outbox.claim_token == job["claim"])
            .with_for_update()
        )
        if row:
            row.state = "failed" if state == "pending" and row.attempts >= 5 else state
            row.next_attempt = time.time() + min(300, 2**row.attempts * 5)
            row.message_id = message_id
            row.claim_token = ""
            row.lease_until = 0
            if row.state != "pending":
                row.payload = ""
    return True


if __name__ == "__main__":
    while True:
        try:
            if not run_once():
                time.sleep(2)
        except Exception as exc:
            logging.error("mail_worker_unavailable error=%s", type(exc).__name__)
            time.sleep(5)
