"""Fixed-recipient SMTP sender for the escalation workflow."""
import base64
from email.message import EmailMessage
from email.utils import make_msgid
import json
import logging
import os
import smtplib
import ssl

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def response(status, payload):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False)}


def handle(event, context):
    try:
        if not isinstance(event, dict) or event.get("httpMethod") != "POST":
            return response(405, {"error": "POST required"})
        raw = event.get("body", "")
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        if len(raw) > 100000:
            return response(413, {"error": "Payload too large"})
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"subject", "body"}:
            return response(400, {"error": "Expected subject and body only"})
        subject, body = data["subject"], data["body"]
        if (not isinstance(subject, str) or not subject.strip()
                or len(subject) > 200 or "\n" in subject or "\r" in subject):
            return response(400, {"error": "Invalid subject"})
        if not isinstance(body, str) or not body.strip() or len(body) > 50000:
            return response(400, {"error": "Invalid body"})
    except (ValueError, TypeError, UnicodeError):
        return response(400, {"error": "Invalid JSON"})

    message = EmailMessage()
    message["From"] = os.environ["HELPDESK_MAILBOX"]
    message["To"] = os.environ["OPERATOR_EMAIL"]
    message["Subject"] = subject
    message["Message-ID"] = make_msgid()
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(body)
    try:
        with smtplib.SMTP_SSL(
            os.environ.get("SMTP_HOST", "smtp.yandex.ru"),
            int(os.environ.get("SMTP_PORT", "465")),
            timeout=15, context=ssl.create_default_context(),
        ) as smtp:
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        LOG.error("DIGEST_FAILED type=SMTPAuthenticationError")
        return response(500, {"error": "SMTP authentication failed"})
    except (smtplib.SMTPException, OSError) as exc:
        LOG.error("DIGEST_FAILED type=%s", type(exc).__name__)
        return response(503, {"error": "SMTP temporarily unavailable"})
    LOG.info("DIGEST_SEND_OK message_id=%s", message["Message-ID"])
    return response(200, {"sent": True, "message_id": message["Message-ID"]})
