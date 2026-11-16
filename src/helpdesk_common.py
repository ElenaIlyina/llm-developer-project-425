"""Shared storage and text masking for both Cloud Functions."""
from datetime import datetime, timezone
import os
import re
import time
import uuid

EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@(?:[\w-]+\.)+[\w-]{2,}", re.I)
CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
PHONE = re.compile(r"(?<!\w)(?:\+?[78][\s().-]*)?(?:\d[\s().-]*){9}\d(?!\w)")
TOKEN = re.compile(r"(?i)\b(password|пароль|token|токен|api[_-]?key)\s*[:=]\s*\S+")

PASSPORT = re.compile(
    r"(?P<label>\b(?:паспорт(?:а)?(?:\s+РФ)?|номер\s+паспорта)[\s:№=-]*)"
    r"(?:серия\s*[:№]?\s*)?\d{2}[ -]?\d{2}\s*[,/-]?\s*(?:(?:номер|№)\s*)?\d{6}\b", re.I)
BADGE = re.compile(
    r"(?P<label>\b(?:номер\s+)?пропуск(?:а)?(?:\s*(?:№|номер|#|:|=))*\s*)"
    r"(?=[A-ZА-ЯЁ0-9._/-]{0,39}\d)[A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9._/-]{0,39}\b", re.I)
ADDRESS = re.compile(
    r"(?P<label>(?<![\w-])адрес(?:\s+(?:проживания|регистрации|доставки))?(?:\s*[:=]\s*|\s+))"
    r"(?P<value>[^\n;]+)", re.I)
STREET_ADDRESS = re.compile(
    r'\b(?i:ул\.?|улица|пр-т|проспект|пер\.?|переулок|шоссе|бульвар)\s*'
    r'[А-ЯЁA-Z0-9][А-ЯЁа-яёA-Za-z0-9 «»".-]{0,80}?,?\s*'
    r'(?i:д(?:ом)?\.?\s*)?\d+[А-ЯЁа-яёA-Za-z]?(?:[/-]\d+)?'
    r'(?:,?\s*(?i:корп(?:ус)?|стр(?:оение)?|кв(?:артира)?)\.?\s*\d+){0,3}')


def _mask_address(match):
    value = match.group("value")
    if value.startswith("[address]"):
        return match.group()
    # "Адрес" also means an email, URL or server address in IT questions.
    # A generic label needs postal evidence; explicit residence labels do not.
    explicit_postal = re.search(r"проживания|регистрации|доставки", match.group("label"), re.I)
    postal_value = re.search(
        r"\b(?:г\.|город\b|ул\.|улица\b|проспект\b|переулок\b|шоссе\b|бульвар\b)"
        r"|,\s*(?:д(?:ом)?\.?\s*)?\d", value, re.I)
    technical_value = re.search(r"https?://|\b(?:электронн\w*|сервера?|сайта?|почты|IP|URL)\b", value, re.I)
    if not explicit_postal and (technical_value or not postal_value):
        return match.group()
    # Preserve the next contact field or a new sentence describing the problem.
    boundary = re.search(
        r"(?i)\b(?:телефон|email|e-mail|паспорт|номер\s+пропуска|пропуск|карта)\b"
        r"|(?<=\d)\.\s+(?=[А-ЯЁA-Z])", value)
    suffix = value[boundary.start():] if boundary else ""
    return match.group("label") + "[address]" + (" " + suffix if suffix else "")


def mask_pii(text):
    text = TOKEN.sub(lambda m: m.group(1) + "=[SECRET]", text)
    text = PASSPORT.sub(lambda m: m.group("label") + "[passport]", text)
    text = BADGE.sub(lambda m: m.group("label") + "[badge]", text)
    text = ADDRESS.sub(_mask_address, text)
    text = STREET_ADDRESS.sub("[address]", text)
    text = EMAIL.sub("[email]", text)
    text = CARD.sub("****-****-****-****", text)
    return PHONE.sub(lambda m: "+7 (***) ***-**-" + re.sub(r"\D", "", m.group())[-2:], text)


def timestamp_text(value):
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value / 1_000_000, timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self):
        import ydb
        self.ydb = ydb
        token = os.environ.get("YC_IAM_TOKEN")
        credentials = (ydb.AccessTokenCredentials(token) if token
                       else ydb.iam.MetadataUrlCredentials())
        self.driver = ydb.Driver(
            endpoint=os.environ["YDB_ENDPOINT"],
            database=os.environ["YDB_DATABASE"],
            credentials=credentials,
        )
        self.driver.wait(timeout=8, fail_fast=True)
        self.pool = ydb.SessionPool(self.driver, size=3)

    def execute(self, query, parameters):
        settings = self.ydb.BaseRequestSettings().with_timeout(8)
        def operation(session):
            prepared = session.prepare(query)
            return session.transaction(self.ydb.SerializableReadWrite()).execute(
                prepared, parameters, commit_tx=True, settings=settings,
            )
        return self.pool.retry_operation_sync(operation)

    def create_ticket(self, user_id, category, text, request_id=None):
        if request_id:
            ticket_id = str(uuid.uuid5(uuid.NAMESPACE_URL, user_id + ":" + request_id))
            return self._create_ticket_once(ticket_id, user_id, category, text)
        ticket_id = str(uuid.uuid4())
        now = time.time_ns() // 1000
        self.execute("""
            DECLARE $id AS Utf8;
            DECLARE $user AS Utf8;
            DECLARE $category AS Utf8;
            DECLARE $text AS Utf8;
            DECLARE $now AS Timestamp;
            UPSERT INTO tickets (id, user_id, category, status, text, created_at, updated_at)
            VALUES ($id, $user, $category, "open", $text, $now, $now);
        """, {"$id": ticket_id, "$user": user_id, "$category": category,
              "$text": mask_pii(text), "$now": now})
        return {"ticket_id": ticket_id, "created_at": timestamp_text(now)}

    def _create_ticket_once(self, ticket_id, user_id, category, text):
        # Read and insert share one serializable transaction. A conflicting concurrent
        # delivery is retried by the pool and then reads the already committed row.
        now = time.time_ns() // 1000
        settings = self.ydb.BaseRequestSettings().with_timeout(8)
        def operation(session):
            lookup = session.prepare("""
                DECLARE $id AS Utf8;
                SELECT id, created_at FROM tickets WHERE id = $id;
            """)
            with session.transaction(self.ydb.SerializableReadWrite()) as tx:
                rows = tx.execute(lookup, {"$id": ticket_id}, settings=settings)[0].rows
                if rows:
                    tx.commit()
                    return {"ticket_id": rows[0].id, "created_at": timestamp_text(rows[0].created_at)}
                insert = session.prepare("""
                    DECLARE $id AS Utf8;
                    DECLARE $user AS Utf8;
                    DECLARE $category AS Utf8;
                    DECLARE $text AS Utf8;
                    DECLARE $now AS Timestamp;
                    INSERT INTO tickets (id, user_id, category, status, text, created_at, updated_at)
                    VALUES ($id, $user, $category, "open", $text, $now, $now);
                """)
                tx.execute(insert, {"$id": ticket_id, "$user": user_id, "$category": category,
                                    "$text": mask_pii(text), "$now": now},
                           commit_tx=True, settings=settings)
                return {"ticket_id": ticket_id, "created_at": timestamp_text(now)}
        return self.pool.retry_operation_sync(operation)

    def list_tickets(self, user_id):
        results = self.execute("""
            DECLARE $user AS Utf8;
            SELECT id, status, category, text, created_at
            FROM tickets VIEW tickets_by_user
            WHERE user_id = $user ORDER BY created_at DESC LIMIT 20;
        """, {"$user": user_id})
        return [
            {"id": row.id, "status": row.status, "category": row.category,
             "text": row.text, "created_at": timestamp_text(row.created_at)}
            for row in results[0].rows
        ]

    def history(self, user_id, limit=10):
        results = self.execute("""
            DECLARE $user AS Utf8;
            DECLARE $limit AS Uint64;
            SELECT id, role, text, created_at FROM messages
            WHERE user_id = $user ORDER BY created_at DESC, id DESC LIMIT $limit;
        """, {"$user": user_id, "$limit": limit})
        return [
            {"role": "assistant" if row.role == "agent" else "user",
             "content": row.text}
            for row in reversed(results[0].rows)
        ]

    def save_message(self, message_id, user_id, role, text, *,
                     model=None, tokens_in=0, tokens_out=0, latency_ms=0):
        self.execute("""
            DECLARE $id AS Utf8;
            DECLARE $user AS Utf8;
            DECLARE $role AS Utf8;
            DECLARE $text AS Utf8;
            DECLARE $model AS Utf8?;
            DECLARE $tokens_in AS Uint64;
            DECLARE $tokens_out AS Uint64;
            DECLARE $latency AS Uint32;
            DECLARE $now AS Timestamp;
            UPSERT INTO messages
              (id, user_id, ticket_id, role, text, model,
               tokens_in, tokens_out, latency_ms, created_at)
            VALUES ($id, $user, NULL, $role, $text, $model,
                    $tokens_in, $tokens_out, $latency, $now);
        """, {"$id": message_id, "$user": user_id, "$role": role,
              "$text": mask_pii(text), "$model": model, "$tokens_in": tokens_in,
              "$tokens_out": tokens_out, "$latency": latency_ms,
              "$now": time.time_ns() // 1000})

    def link_ticket(self, user_id, message_ids, ticket_id):
        self.execute("""
            DECLARE $user AS Utf8;
            DECLARE $first AS Utf8;
            DECLARE $second AS Utf8;
            DECLARE $ticket AS Utf8;
            UPDATE messages SET ticket_id = $ticket
            WHERE user_id = $user AND (id = $first OR id = $second);
        """, {"$user": user_id, "$first": message_ids[0],
              "$second": message_ids[1], "$ticket": ticket_id})


_STORE = None


def get_store():
    global _STORE
    if _STORE is None:
        _STORE = Store()
    return _STORE
