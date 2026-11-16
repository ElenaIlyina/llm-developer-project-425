"""Bounded PII cleanup; default read-only, --apply updates text fields only."""
import argparse
import json
from qa_common import ROOT, configure_cloud
from helpdesk_common import get_store, mask_pii


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    configure_cloud()
    store = get_store()
    # Refuse before any mutations if this small-project migration needs pagination.
    tables = {}
    for table in ('tickets', 'messages'):
        columns = 'id,user_id,text'
        rows = store.execute(f'SELECT {columns} FROM {table} LIMIT 1001;', {})[0].rows
        if len(rows) > 1000:
            raise RuntimeError('Migration requires pagination; no rows modified')
        tables[table] = rows
    report = {'mode': 'apply' if args.apply else 'dry-run', 'tables': {}}
    for table, rows in tables.items():
        changes = [(row, mask_pii(row.text)) for row in rows if mask_pii(row.text) != row.text]
        report['tables'][table] = {'scanned': len(rows), 'needs_masking': len(changes), 'updated': 0}
        if not args.apply:
            continue
        for row, masked in changes:
            params = {'$id': row.id, '$old': row.text, '$new': masked}
            declarations = 'DECLARE $id AS Utf8; DECLARE $old AS Utf8; DECLARE $new AS Utf8; '
            condition = 'id=$id AND text=$old'
            if table == 'messages':
                declarations += 'DECLARE $u AS Utf8; '
                params['$u'] = row.user_id
                condition += ' AND user_id=$u'
            store.execute(declarations + f'UPDATE {table} SET text=$new WHERE {condition};', params)
            report['tables'][table]['updated'] += 1
    # Verify the final scan without printing or saving original personal data.
    if args.apply:
        for table in ('tickets', 'messages'):
            rows = store.execute(f'SELECT text FROM {table} LIMIT 1001;', {})[0].rows
            assert len(rows) <= 1000 and all(mask_pii(r.text) == r.text for r in rows)
        report['remaining_detectable_pii'] = 0
        (ROOT / 'docs/evidence/additional-pii-cleanup.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('PII cleanup failed: ' + type(exc).__name__) from None
