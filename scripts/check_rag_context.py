"""Read-only RAG regression with empty and actual operator history; no SMTP."""
import json
import os
from unittest.mock import patch
from qa_common import ROOT, configure_cloud
from check_qa_flow import response_trace
import email_poller as poller
from helpdesk_common import get_store


def main():
    token = configure_cloud()
    user = os.environ['OPERATOR_EMAIL'].casefold()
    stored = get_store().history(user)
    original = poller.request_json
    report = {'smtp_used': False, 'ydb_writes': False, 'cases': [], 'passed': False}
    try:
        for name, history in [('empty_history', []), ('stored_history', stored)]:
            traces = []
            def capture(url, **kwargs):
                response = original(url, **kwargs)
                traces.append(response_trace(response))
                return response
            with patch.object(poller, 'request_json', side_effect=capture):
                answer = poller.agent_answer('У меня сломался принтер, что делать?', token, user, history)
            case = {'name': name, 'history_available': len(history), 'reply': answer['text'],
                    'searches': answer['searches'], 'sources': answer['sources'], 'trace': traces}
            report['cases'].append(case)
            assert answer['searches'], 'Search was skipped'
            assert any(s['filename'] == 'printer.md' for s in answer['sources']), 'No verified printer source'
        report['passed'] = True
    finally:
        (ROOT / 'docs/evidence/review-rag-context.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('RAG context passed: fresh printer search with empty and stored history; no mail or DB writes.')


if __name__ == '__main__':
    main()
