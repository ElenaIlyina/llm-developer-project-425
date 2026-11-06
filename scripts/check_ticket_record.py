"""Read-only diagnosis of a ticket mentioned in an email; no addresses are printed."""
import argparse
import json
import os
import uuid
from qa_common import configure_cloud
from helpdesk_common import get_store, mask_pii, timestamp_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('ticket_id')
    args = parser.parse_args()
    ticket_id = str(uuid.UUID(args.ticket_id))
    configure_cloud()
    store = get_store()
    rows = store.execute('''DECLARE $id AS Utf8;
        SELECT id,user_id,status,category,text,created_at FROM tickets WHERE id=$id;
    ''', {'$id': ticket_id})[0].rows
    operator = os.environ.get('OPERATOR_EMAIL', '').casefold()
    ticket = None
    if rows:
        r = rows[0]
        ticket = dict(id=r.id, status=r.status, category=r.category, text=mask_pii(r.text),
                      created_at=timestamp_text(r.created_at),
                      owner_matches_operator=r.user_id.casefold() == operator)
    messages = store.execute('''DECLARE $u AS Utf8;
        SELECT id,role,ticket_id,text,created_at FROM messages
        WHERE user_id=$u ORDER BY created_at DESC LIMIT 8;
    ''', {'$u': operator})[0].rows
    report = dict(queried_ticket_id=ticket_id, ticket_found=bool(rows), ticket=ticket,
                  recent_operator_messages=[dict(id=r.id, role=r.role, ticket_id=r.ticket_id,
                      text=mask_pii(r.text), created_at=timestamp_text(r.created_at)) for r in messages])
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Ticket diagnosis failed: ' + type(exc).__name__) from None
