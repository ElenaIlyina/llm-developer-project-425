import json
import os
import unittest
from unittest.mock import MagicMock, patch
from src.helpdesk_common import Store, mask_pii
from src import email_poller as poller, rag
from test_email_poller import ENV, incoming


class ExtendedPrivacyTests(unittest.TestCase):
    def test_technical_address_questions_keep_their_meaning(self):
        for text in ('Как изменить адрес электронной почты?',
                     'Не открывается адрес https://intranet.example.org. Не могу войти в систему.',
                     'Адрес сервера: 10.0.0.1. VPN не подключается.'):
            with self.subTest(text=text):
                self.assertEqual(mask_pii(text), text)

    def test_passport_is_not_misclassified_as_a_phone(self):
        for text in ['Паспорт: 1122 333444', 'Паспорт РФ №11 22 333444', 'Паспорт: №11 22 333444',
                     'Номер паспорта: серия 1122 номер 333444']:
            masked = mask_pii(text)
            self.assertIn('[passport]', masked)
            self.assertNotIn('333444', masked)
            self.assertNotIn('***-**-44', masked)
            self.assertEqual(mask_pii(masked), masked)

    def test_badge_and_postal_address_preserve_problem_text(self):
        original = 'Пропуск №TEST-12345; Адрес: г. Примерск, ул. Учебная, д. 12, кв. 34. Принтер не печатает.'
        masked = mask_pii(original)
        self.assertIn('[badge]', masked)
        self.assertIn('[address]', masked)
        self.assertNotIn('TEST-12345', masked)
        self.assertNotIn('Учебная', masked)
        self.assertIn('Принтер не печатает.', masked)
        self.assertEqual(mask_pii(masked), masked)
        self.assertEqual(mask_pii('Пропуск не работает'), 'Пропуск не работает')

    def test_unlabelled_street_and_following_contact_are_masked(self):
        self.assertNotIn('Учебная', mask_pii('Живу на ул. Учебная, д. 12, кв. 34'))
        compact = mask_pii('ул.Учебная,д.12,кв.34')
        self.assertEqual(compact, '[address]')
        self.assertEqual(mask_pii('IP-адрес: 10.0.0.1'), 'IP-адрес: 10.0.0.1')
        value = mask_pii('Адрес: г. Примерск, ул. Учебная, д. 12, email test@example.invalid')
        self.assertIn('[address]', value)
        self.assertIn('[email]', value)
        self.assertEqual(mask_pii(value), value)

    def test_both_storage_boundaries_hide_new_fields(self):
        store = Store.__new__(Store)
        store.execute = MagicMock()
        text = 'Паспорт 1122 333444; Номер пропуска: TEST-12345; Адрес: ул. Учебная, д. 12'
        store.create_ticket('employee@example.org', 'bug', text)
        created = store.execute.call_args.args[1]['$text']
        store.save_message('id', 'employee@example.org', 'user', text)
        saved = store.execute.call_args.args[1]['$text']
        for result in (created, saved):
            for marker in ('[passport]', '[badge]', '[address]'):
                self.assertIn(marker, result)
            for raw in ('333444', 'TEST-12345', 'Учебная'):
                self.assertNotIn(raw, result)


class ScopeTests(unittest.TestCase):
    @patch.dict(os.environ, ENV)
    def test_uncited_draft_with_unknown_phrase_never_publishes_instructions(self):
        for draft in ('Не знаю правил доступа к YouTube, но попробуйте перезапустить VPN и сменить сервер.',
                      'Перезапустите VPN и смените сервер.'):
            response = dict(output=[dict(type='file_search_call', status='completed', results=[]),
                dict(type='message', role='assistant', content=[dict(type='output_text', text=draft)])])
            with patch.object(poller, 'request_json', return_value=response), patch.object(poller, 'verify_support') as verify:
                result = poller.agent_answer('Как смотреть YouTube через VPN?', 'fake', 'employee@example.org', [])
            self.assertEqual(result['text'], 'Не знаю: в базе знаний нет этой информации. Хотите создать тикет для уточнения?')
            self.assertEqual(result['sources'], [])
            verify.assert_not_called()

    @patch.dict(os.environ, ENV)
    def test_failed_search_does_not_claim_no_information(self):
        response = dict(output=[dict(type='file_search_call', status='failed', results=[]),
            dict(type='message', role='assistant', content=[dict(type='output_text', text='Не знаю. Перезапустите VPN.')])])
        with patch.object(poller, 'request_json', return_value=response):
            result = poller.agent_answer('Как смотреть YouTube через VPN?', 'fake', 'employee@example.org', [])
        self.assertIn('поиск не завершён', result['text'])
        self.assertNotIn('Перезапустите', result['text'])

    @patch.dict(os.environ, ENV)
    def test_scope_classifier_checks_specific_question_and_actual_snippets(self):
        response = dict(output=[dict(type='file_search_call', results=[
            dict(filename='vpn.md', text='Если VPN не подключается: проверьте интернет.')])])
        with patch('src.guardrails.request_json', return_value=dict(result=dict(alternatives=[dict(message=dict(text=json.dumps(dict(supported=False, quote='', reason='different problem'))))]))) as classify:
            verdict = rag.verify_support(response, [dict(filename='vpn.md')],
                                         'Как смотреть YouTube через VPN?', 'Перезапустите VPN.', 'fake')
        self.assertFalse(verdict)
        data = classify.call_args.kwargs['data']
        self.assertIn('YouTube', json.loads(data['messages'][1]['text'])['question'])
        self.assertIn('не подключается', json.loads(data['messages'][1]['text'])['documents'][0]['text'])
        self.assertNotIn('Как смотреть YouTube через VPN?', data['messages'][0]['text'])

    @patch.dict(os.environ, ENV)
    def test_valid_citation_to_wrong_topic_becomes_unknown_without_link(self):
        response = dict(output=[dict(type='file_search_call', results=[]),
            dict(type='message', role='assistant', content=[dict(type='output_text',
                text='Перезапустите VPN-клиент.\nДокумент: vpn.md',
                annotations=[dict(type='file_citation', filename='vpn.md', file_id='file')])])])
        with patch.object(poller, 'request_json', return_value=response), patch.object(poller, 'verify_support', return_value=False):
            result = poller.agent_answer('Как смотреть YouTube через VPN?', 'fake', 'employee@example.org', [])
        self.assertIn('Не знаю', result['text'])
        self.assertIn('Хотите создать тикет', result['text'])
        self.assertNotIn('Перезапустите', result['text'])
        self.assertEqual(result['sources'], [])
        self.assertIsNone(result['ticket_id'])

    @patch.dict(os.environ, ENV)
    def test_verifier_outage_is_not_reported_as_absence_of_knowledge(self):
        response = dict(output=[dict(type='file_search_call', results=[]),
            dict(type='message', role='assistant', content=[dict(type='output_text',
                text='Проверьте интернет.\nДокумент: vpn.md',
                annotations=[dict(type='file_citation', filename='vpn.md')])])])
        with patch.object(poller, 'request_json', return_value=response), patch.object(poller, 'verify_support', return_value=None):
            result = poller.agent_answer('VPN не подключается', 'fake', 'employee@example.org', [])
        self.assertIn('Не удалось подтвердить', result['text'])
        self.assertNotIn('нет этой информации', result['text'])
        self.assertEqual(result['sources'], [])

    @patch.dict(os.environ, ENV)
    def test_supported_verdict_requires_a_verbatim_source_quote(self):
        response = dict(output=[dict(type='file_search_call', results=[
            dict(filename='vpn.md', text='Проверьте интернет.')])])
        fake = dict(result=dict(alternatives=[dict(message=dict(text=json.dumps(
            dict(supported=True, quote='Перезагрузите сервер', reason='invented'))))]))
        with patch('src.guardrails.request_json', return_value=fake):
            self.assertIsNone(rag.verify_support(response, [dict(filename='vpn.md')],
                              'VPN не работает', 'Проверьте интернет.', 'fake'))

    @patch.dict(os.environ, ENV)
    def test_verification_usage_is_separate_from_primary_response(self):
        response = dict(output=[dict(type='file_search_call', results=[
            dict(filename='vpn.md', text='Проверьте интернет.')])])
        fake = dict(result=dict(alternatives=[dict(message=dict(text=json.dumps(
            dict(supported=True, quote='Проверьте интернет.', reason='grounded'))))],
            usage=dict(inputTextTokens='10', completionTokens='3', totalTokens='13')))
        metrics = {}
        with patch('src.guardrails.request_json', return_value=fake):
            self.assertTrue(rag.verify_support(response, [dict(filename='vpn.md')],
                            'VPN не работает', 'Проверьте интернет.', 'fake', metrics=metrics))
        self.assertEqual(metrics['usage']['totalTokens'], '13')

    def test_source_quote_can_span_numbered_paragraphs_without_invented_sentences(self):
        fragments = [dict(text='1. Проверьте интернет.\n2. Перезапустите VPN-клиент.\n3. Создайте заявку.')]
        self.assertTrue(rag._quote_supported('Проверьте интернет. Создайте заявку.', fragments))
        self.assertFalse(rag._quote_supported('Проверьте интернет. Перезапустите сервер.', fragments))


class FailureNoticeTests(unittest.TestCase):
    def run_failure(self, process_error=None, notice_error=None, token_error=None, storage_error=None):
        imap = MagicMock()
        imap.uid.side_effect = lambda op, *a: ('OK', [b'1']) if op == 'search' else (
            ('OK', [(b'BODY', incoming().as_bytes())]) if op == 'fetch' else ('OK', []))
        with patch.dict(os.environ, ENV), patch.object(poller, 'connect_mailbox') as connection, \
                patch.object(poller, 'get_token', return_value='fake', side_effect=token_error), \
                patch.object(poller, 'process_message', side_effect=process_error), \
                patch.object(poller, 'send_reply', side_effect=notice_error) as notice, \
                patch.object(poller, 'get_store', side_effect=storage_error):
            connection.return_value.__enter__.return_value = imap
            with self.assertLogs(poller.LOG, 'INFO') as logs:
                result = poller.handle({}, None)
        return result, notice, imap, logs.output

    def test_processing_failure_sends_safe_notice_and_marks_seen(self):
        result, notice, imap, logs = self.run_failure(process_error=RuntimeError('password=must-not-leak'))
        self.assertEqual(result['failed'], 1)
        notice.assert_called_once()
        self.assertEqual(notice.call_args.args[1], 'employee@example.org')
        text = notice.call_args.args[2]
        self.assertIn('технического сбоя', text)
        self.assertIn('могло выполниться', text)
        self.assertNotIn('must-not-leak', text + str(logs))
        self.assertTrue(any(c.args[0] == 'store' for c in imap.uid.call_args_list))

    def test_token_failure_also_notifies_without_ydb_dependency(self):
        _, notice, _, _ = self.run_failure(token_error=TimeoutError())
        notice.assert_called_once()

    def test_smtp_outage_does_not_loop_or_expose_errors(self):
        result, notice, imap, logs = self.run_failure(process_error=RuntimeError(), notice_error=OSError('private@example.org'))
        self.assertEqual(result['failed'], 1)
        notice.assert_called_once()
        self.assertIn('FAILURE_NOTICE_FAILED', str(logs))
        self.assertNotIn('private@example.org', str(logs))

    def test_fetch_failure_never_sends_to_previous_message_sender(self):
        imap = MagicMock()
        def command(op, *args):
            if op == 'search': return 'OK', [b'1 2']
            if op == 'fetch':
                return ('OK', [(b'BODY', incoming().as_bytes())]) if args[0] == b'1' else ('NO', [])
            return 'OK', []
        imap.uid.side_effect = command
        with patch.dict(os.environ, ENV), patch.object(poller, 'connect_mailbox') as connection, \
                patch.object(poller, 'get_token', return_value='fake'), patch.object(poller, 'process_message'), \
                patch.object(poller, 'send_reply') as notice:
            connection.return_value.__enter__.return_value = imap
            poller.handle({}, None)
        notice.assert_not_called()

    def test_storage_outage_does_not_prevent_failure_email(self):
        _, notice, _, logs = self.run_failure(process_error=TimeoutError(), storage_error=TimeoutError())
        notice.assert_called_once()
        self.assertIn('FAILURE_NOTICE_STORAGE_FAILED', str(logs))
