"""IMAP -> Responses API + MCP/YDB -> SMTP poller (Python 3.12)."""
import email
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, make_msgid
from html.parser import HTMLParser
import imaplib
import json
import logging
import os
import re
from pathlib import Path
import smtplib
import ssl
import time
import uuid

try:
    from helpdesk_common import get_store, mask_pii
    from rag import search_tool, search_trace, cited_sources, add_source_links
    from guardrails import classify_text
except ImportError:
    from src.helpdesk_common import get_store, mask_pii
    from src.rag import search_tool, search_trace, cited_sources, add_source_links
    from src.guardrails import classify_text
from urllib.request import Request, urlopen

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("br", "p", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def message_text(message):
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        raise ValueError("No supported message body")
    text = body.get_content()
    if body.get_content_type() == "text/html":
        parser = TextHTML()
        parser.feed(text)
        text = "".join(parser.parts)
    text = text.strip()
    if not text:
        raise ValueError("Empty message")
    return text[:12000]


def request_json(url, data=None, headers=None, timeout=25):
    payload = None if data is None else json.dumps(data).encode("utf-8")
    request = Request(url, data=payload, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def get_token():
    return request_json(
        "http://169.254.169.254/computeMetadata/v1/instance/"
        "service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
        timeout=3,
    )["access_token"]


def parse_tool_output(value):
    if isinstance(value, str):
        try:
            return parse_tool_output(json.loads(value))
        except (ValueError, TypeError):
            return None
    if isinstance(value, dict):
        if value.get("ticket_id"):
            return value["ticket_id"]
        for part in value.get("content", []):
            ticket = parse_tool_output(part.get("text", ""))
            if ticket:
                return ticket
    return None


def ticket_creation_requested(text, history):
    """Conservative routing gate; ambiguous wording keeps creation unavailable."""
    text = re.split(r"(?m)^\s*-{8,}\s*$", text, maxsplit=1)[0].casefold().strip()
    if re.search(r"\b(?:не|нельзя|запрещено)\s+(?:созда|оформ|завод|завест|регистр)", text):
        return False
    if re.search(r"\b(?:создай|создайте|оформи|оформите|заведи|заведите|зарегистрируй)\b.{0,60}\b(?:тикет|заявк)", text):
        return True
    # A short affirmative is valid only immediately after an assistant's offer.
    if re.fullmatch(r"(?:да|согласен|согласна|согласен на создание заявки|согласна на создание заявки)[.! ]*", text):
        if history and history[-1].get("role") == "assistant":
            offer = history[-1].get("content", "")
            return isinstance(offer, str) and bool(re.search(
                r"(?:создать|создам|создания).{0,40}(?:тикет|заявк)", offer.casefold()))
    return False


def agent_answer(text, token, user_id, history):
    prompt_path = Path(__file__).with_name("help-desk-system.md")
    if not prompt_path.exists():
        prompt_path = Path(__file__).resolve().parents[1] / "prompts/help-desk-system.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    model = os.environ.get("YC_MODEL", "gpt://" + os.environ["YC_FOLDER_ID"] + "/yandexgpt/latest")
    create_requested = ticket_creation_requested(text, history)
    current_text = re.split(r"(?m)^\s*-{8,}\s*$", text, maxsplit=1)[0]
    list_requested = bool(re.search(r"(?:покажи|покажите|список|статус|мои).{0,40}(?:тикет|заявк)", current_text.casefold()))
    tool_choice = ({"type": "mcp", "server_label": "ydb-tickets", "name": "create-ticket"}
                   if create_requested else
                   {"type": "mcp", "server_label": "ydb-tickets", "name": "list-my-tickets"}
                   if list_requested else {"type": "file_search"})
    payload = {
        "tool_choice": tool_choice,
        "model": model,
        "instructions": prompt,
        "input": [{"role": "user", "content": json.dumps(
            {"sender_email": user_id, "message": mask_pii(current_text),
             "conversation_history": [
                 {"role": item["role"], "content": mask_pii(item["content"])}
                 for item in history]}, ensure_ascii=False)}],
        "max_output_tokens": 1200,
        "store": False,
        "tools": [{
            "type": "mcp", "server_label": "ydb-tickets",
            "server_url": os.environ["MCP_SERVER_URL"], "require_approval": "never",
            "allowed_tools": (["list-my-tickets", "create-ticket"]
                              if create_requested else ["list-my-tickets"]),
        }, search_tool()],
    }
    LOG.info("REQUEST_PAYLOAD history_count=%d roles=%s",
             len(history), ",".join(item["role"] for item in payload["input"]))
    started = time.monotonic()
    response = request_json(
        "https://ai.api.cloud.yandex.net/v1/responses",
        data=payload,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json",
                 "OpenAI-Project": os.environ["YC_FOLDER_ID"]},
        timeout=45,
    )
    latency = int((time.monotonic() - started) * 1000)
    moderation_blocked = (response.get("status") == "incomplete" and
                          (response.get("incomplete_details") or {}).get("reason") == "content_filter")
    if moderation_blocked:
        LOG.warning("AI_STUDIO_CONTENT_FILTER")
    elif response.get("status") not in (None, "completed"):
        raise ValueError("Incomplete agent response")
    ticket_id = None
    searches = []
    for item in response.get("output", []):
        if item.get("type") == "file_search_call":
            trace = search_trace(item, mask_pii)
            searches.append(trace)
            LOG.info("file_search_call %s", json.dumps(trace, ensure_ascii=False))
        if item.get("type") == "mcp_approval_request":
            raise ValueError("Unexpected MCP approval request")
        if item.get("type") != "mcp_call":
            continue
        LOG.info("mcp_call name=%s error=%s", item.get("name"), bool(item.get("error")))
        if item.get("error"):
            raise ValueError("MCP tool failed")
        if item.get("name") == "create-ticket":
            candidate = parse_tool_output(item.get("output"))
            if candidate:
                ticket_id = str(uuid.UUID(candidate))
    answer = "\n".join(
        part["text"]
        for item in response.get("output", [])
        if item.get("type") == "message" and item.get("role") == "assistant"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    ).strip()
    if not answer and moderation_blocked:
        answer = "Не могу обработать это обращение: сработало правило модерации."
    if not answer:
        raise ValueError("No agent response text")
    if create_requested:
        # A model-written UUID is never evidence of a completed action.
        answer = ("Тикет с идентификатором " + ticket_id + " успешно создан."
                  if ticket_id else
                  "Создание тикета не подтверждено: инструмент не вернул номер заявки. Попробуйте позже.")
    sources = cited_sources(response)
    if not create_requested and not list_requested and not moderation_blocked:
        if not searches:
            answer = "Не удалось проверить базу знаний: поиск не выполнен. Попробуйте позже."
        elif not sources and "не знаю" not in answer.casefold():
            answer = ("Не удалось подготовить ответ с подтверждённым источником из базы знаний. "
                      "Хотите создать тикет для уточнения?")
    LOG.info("RAG_SOURCES %s", json.dumps(sources, ensure_ascii=False))
    answer = mask_pii(add_source_links(answer, sources))
    usage = response.get("usage", {})
    return {
        "text": answer, "ticket_id": ticket_id, "model": model,
        "tokens_in": int(usage.get("input_tokens") or 0),
        "tokens_out": int(usage.get("output_tokens") or 0), "latency_ms": latency,
        "searches": searches, "sources": sources,
    }


def skip_message(message, sender):
    own = {os.environ["HELPDESK_MAILBOX"].casefold(),
           os.environ["IMAP_USER"].casefold(),
           os.environ["SMTP_USER"].casefold()}
    return (
        not sender or "@" not in sender or sender.casefold() in own
        or message.get("Auto-Submitted", "no").lower() != "no"
        or message.get("Precedence", "").lower() in ("bulk", "list", "junk")
        or bool(message.get("List-Id"))
        or message.get_content_type() == "multipart/report"
    )


def send_reply(message, recipient, answer):
    reply = EmailMessage()
    reply["From"] = os.environ["HELPDESK_MAILBOX"]
    reply["To"] = recipient
    subject = str(message.get("Subject", "Без темы"))
    reply["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
    reply["Message-ID"] = make_msgid()
    reply["Auto-Submitted"] = "auto-replied"
    original_id = message.get("Message-ID")
    if original_id:
        reply["In-Reply-To"] = str(original_id)
        reply["References"] = str(original_id)
    reply.set_content(answer)
    with smtplib.SMTP_SSL(
        os.environ.get("SMTP_HOST", "smtp.yandex.ru"),
        int(os.environ.get("SMTP_PORT", "465")),
        timeout=10, context=ssl.create_default_context(),
    ) as smtp:
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(reply)


def mark_seen(imap, uid):
    status, _ = imap.uid("store", uid, "+FLAGS", "(\\Seen)")
    if status != "OK":
        raise RuntimeError("Unable to mark message seen")


def process_message(message, sender, token, source_id):
    store = get_store()
    user_id = sender.casefold()
    history = store.history(user_id)
    text = message_text(message)
    user_message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, source_id + ":user"))
    agent_message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, source_id + ":agent"))
    store.save_message(user_message_id, user_id, "user", text)
    label = classify_text(text, token=token)
    if label == "safe":
        result = agent_answer(text, token, user_id, history)
    else:
        reply = ("Не могу выполнить инструкции по обходу правил или неразрешённым действиям. "
                 "Опишите рабочую проблему — помогу в рамках Help Desk."
                 if label == "injection" else
                 "Я помогаю с рабочими вопросами HR, IT и администрирования. "
                 "Сформулируйте, пожалуйста, обращение по этим темам.")
        result = {"text": reply, "ticket_id": None, "model": "guardrail/" + label,
                  "tokens_in": 0, "tokens_out": 0, "latency_ms": 0}
    store.save_message(
        agent_message_id, user_id, "agent", result["text"],
        model=result["model"], tokens_in=result["tokens_in"],
        tokens_out=result["tokens_out"], latency_ms=result["latency_ms"],
    )
    if result["ticket_id"]:
        store.link_ticket(user_id, [user_message_id, agent_message_id], result["ticket_id"])
    LOG.info("AGENT_OK len=%d history_count=%d tokens_in=%d tokens_out=%d latency_ms=%d",
             len(result["text"]), len(history), result["tokens_in"],
             result["tokens_out"], result["latency_ms"])
    send_reply(message, sender, result["text"])


def connect_mailbox():
    for attempt in range(2):
        imap = None
        try:
            imap = imaplib.IMAP4_SSL(
                os.environ.get("IMAP_HOST", "imap.yandex.ru"), 993,
                ssl_context=ssl.create_default_context(), timeout=10,
            )
            imap.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
            status, _ = imap.select("INBOX")
            if status != "OK":
                raise RuntimeError("Unable to select INBOX")
            return imap
        except (imaplib.IMAP4.abort, OSError):
            if imap is not None:
                try:
                    imap.shutdown()
                except Exception:
                    pass
            if attempt:
                raise
            LOG.warning("IMAP_CONNECT_RETRY")
    raise RuntimeError("Unable to connect to INBOX")


def handle(event, context):
    # Start another message only while enough time remains in the 120-second budget.
    started = time.monotonic()
    counts = {"processed": 0, "failed": 0, "skipped": 0}
    token = None
    with connect_mailbox() as imap:
        status, data = imap.uid("search", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Unable to search INBOX")
        uids = data[0].split() if data and data[0] else []
        LOG.info("GOT_UNSEEN=%d", len(uids))
        for uid in uids[:5]:
            if time.monotonic() - started > 20:
                break
            try:
                status, fetched = imap.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK":
                    raise RuntimeError("Unable to fetch message")
                raw = next(part[1] for part in fetched if isinstance(part, tuple))
                message = email.message_from_bytes(raw, policy=policy.default)
                sender = parseaddr(str(message.get("From", "")))[1]
                LOG.info("MSG uid=%s", uid.decode("ascii"))
                if skip_message(message, sender):
                    counts["skipped"] += 1
                else:
                    if token is None:
                        token = get_token()
                    uid_validity = imap.response("UIDVALIDITY")[1]
                    source_id = os.environ["HELPDESK_MAILBOX"] + ":" + str(uid_validity) + ":" + uid.decode("ascii")
                    process_message(message, sender, token, source_id)
                    LOG.info("SEND_OK uid=%s", uid.decode("ascii"))
                    counts["processed"] += 1
            except Exception as exc:
                # Do not log mail contents, passwords, tokens or API error payloads.
                LOG.error("MSG_FAILED uid=%s type=%s", uid.decode("ascii"), type(exc).__name__)
                counts["failed"] += 1
            # Course MVP policy: failed messages are also marked read.
            mark_seen(imap, uid)
    return counts
