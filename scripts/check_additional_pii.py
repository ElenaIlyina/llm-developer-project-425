"""Check deployed ticket masking and local Store against real YDB; remove fixtures."""
import json
import uuid
from qa_common import ROOT, configure_cloud
from helpdesk_common import get_store
from email_poller import call_create_ticket, parse_tool_output


def main():
    token = configure_cloud()
    store = get_store()
    user = 'pii-check-' + uuid.uuid4().hex + '@example.invalid'
    text = ('Тестовый принтер не печатает. Паспорт: 1122 333444; '
            'Пропуск №TEST-12345; Адрес: г. Москва, ул. Учебная, д. 12, кв. 34')
    report = {'smtp_used': False, 'synthetic_fixture': True,
              'ticket_path': 'deployed MCP function', 'message_path': 'local Store to real YDB'}
    try:
        result = call_create_ticket({'user_id': user, 'category': 'bug', 'text': text,
                                     'request_id': str(uuid.uuid4())}, token)
        ticket_id = parse_tool_output(result)
        assert ticket_id
        store.save_message(str(uuid.uuid4()), user, 'user', text)
        checks = {}
        for table in ('tickets', 'messages'):
            rows = store.execute('DECLARE $u AS Utf8; SELECT text FROM ' + table +
                                 ' WHERE user_id=$u;', {'$u': user})[0].rows
            checks[table] = len(rows) == 1 and all(
                mask in rows[0].text for mask in ('[passport]', '[badge]', '[address]')) and all(
                raw not in rows[0].text for raw in ('1122', '333444', 'TEST-12345', 'Учебная'))
        report['checks'] = checks
        assert all(checks.values()), 'Masking boundary failed'
        report['passed'] = True
    finally:
        for table in ('messages', 'tickets'):
            store.execute('DECLARE $u AS Utf8; DELETE FROM ' + table + ' WHERE user_id=$u;',
                          {'$u': user})
        report['synthetic_rows_removed'] = True
        (ROOT / 'docs/evidence/additional-pii-storage-check.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
