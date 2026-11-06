"""JSON actions used by direct invoke, API Gateway and MCP Hub."""
import base64
import json
import logging
from email.utils import parseaddr

try:
    from helpdesk_common import get_store
    from guardrails import classify_text
except ImportError:
    from src.helpdesk_common import get_store
    from src.guardrails import classify_text

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def arguments(event):
    if not isinstance(event, dict):
        raise ValueError("Expected a JSON object")
    if "httpMethod" in event:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        event = json.loads(body)
    if not isinstance(event, dict):
        raise ValueError("Expected a JSON object")
    return event


def handle(event, context):
    http = isinstance(event, dict) and "httpMethod" in event
    try:
        args = arguments(event)
        action = args.get("action")
        if action is None:
            action = "create-ticket" if ("text" in args or "category" in args) else "list-my-tickets"
        if action not in ("create-ticket", "list-my-tickets"):
            raise ValueError("Unknown action")
        user_id = args.get("user_id")
        if not isinstance(user_id, str) or len(user_id) > 254:
            raise ValueError("Invalid user_id")
        if parseaddr(user_id)[1] != user_id or "@" not in user_id:
            raise ValueError("user_id must be an email address")
        user_id = user_id.strip().casefold()
        if action == "create-ticket":
            category, text = args.get("category"), args.get("text")
            if category not in ("bug", "docs", "feature", "access"):
                raise ValueError("category must be bug, docs, feature or access")
            if not isinstance(text, str) or not text.strip() or len(text) > 12000:
                raise ValueError("text must contain 1..12000 characters")
            if classify_text(text) == "injection":
                blocked = {"error": "INJECTION_BLOCKED", "blocked": True}
                if not http:
                    return blocked
                return {"statusCode": 422, "headers": {"Content-Type": "application/json"},
                        "body": json.dumps(blocked)}
            result = get_store().create_ticket(user_id, category, text.strip())
        else:
            result = get_store().list_tickets(user_id)
        LOG.info("ACTION_OK action=%s", action)
        if not http:
            return result
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(result, ensure_ascii=False)}
    except (ValueError, TypeError) as exc:
        if not http:
            raise ValueError(str(exc)) from None
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(exc)})}
