import unittest
from scripts.qa_metrics import compare_usage, generation_cost, summarize
from scripts.qa_report import monthly_estimate
from scripts.check_qa_flow import response_trace


class QaTests(unittest.TestCase):
    def test_usage_requires_real_fields_and_exact_match(self):
        stored = dict(tokens_in=14, tokens_out=2, latency_ms=50)
        self.assertTrue(all(compare_usage(dict(input_tokens=14, output_tokens=2, total_tokens=16), stored).values()))
        self.assertFalse(compare_usage(dict(input_tokens=15, output_tokens=2, total_tokens=17), stored)['input_matches'])
        with self.assertRaises(ValueError):
            compare_usage({}, stored)

    def test_guardrail_is_not_counted_as_generation(self):
        rows = [dict(role='agent', model='guardrail/injection', tokens_in=0, tokens_out=0, latency_ms=0),
                dict(role='agent', model='gpt://folder/yandexgpt/latest', tokens_in=100, tokens_out=20, latency_ms=30)]
        summary = summarize(rows)
        self.assertEqual(summary['generation_responses'], 1)
        self.assertEqual(summary['guardrail_responses'], 1)
        self.assertEqual(summary['tokens_in'], 100)
        self.assertEqual(generation_cost(100, 20, 1.2, 1.2), 0.144)

    def test_trace_excludes_headers_and_masks_tool_arguments(self):
        trace = response_trace(dict(headers={'Authorization': 'secret'}, output=[dict(
            type='mcp_call', name='create-ticket', arguments='{"user_id":"qa@example.invalid","text":"mail test@example.org"}')]))
        self.assertNotIn('headers', trace)
        self.assertEqual(trace['output'][0]['arguments']['user_id'], '[email]')
        self.assertEqual(trace['output'][0]['arguments']['text'], 'mail [email]')

    def test_monthly_scenario_has_explicit_limits(self):
        import json
        from scripts.qa_common import ROOT
        rates = json.loads((ROOT / 'config/pricing-2026-11-06.json').read_text())
        result = monthly_estimate(dict(generation_responses=1, tokens_in=100, tokens_out=20), rates)
        self.assertEqual(result['poller_calls'], 43200)
        self.assertEqual(result['known_components_rub']['index_storage'], 318)
        self.assertFalse(result['is_total_invoice'])
        self.assertGreater(result['functions_rub_if_allowance_exhausted'], result['functions_rub_if_allowance_available'])
        doubled = monthly_estimate(dict(generation_responses=1, tokens_in=100, tokens_out=20), rates, classifier_tokens=1001)
        self.assertEqual(doubled['known_components_rub']['classifier'], round(2 * result['known_components_rub']['classifier'], 4))

    def test_tool_tokens_explain_yandex_total(self):
        usage = dict(input_tokens=955, output_tokens=92, total_tokens=2138,
                     input_tokens_details=dict(tool_tokens=1091))
        self.assertTrue(all(compare_usage(usage, dict(tokens_in=955, tokens_out=92, latency_ms=4589)).values()))

    def test_creation_gate_requires_request_or_contextual_consent(self):
        from src.email_poller import ticket_creation_requested
        self.assertFalse(ticket_creation_requested('У меня сломался принтер, что делать?', []))
        self.assertFalse(ticket_creation_requested('Не создавай тикет', []))
        self.assertFalse(ticket_creation_requested('Не надо создавать заявку', []))
        self.assertFalse(ticket_creation_requested('Да', []))
        self.assertTrue(ticket_creation_requested('Не помогло, создай тикет категории bug', []))
        self.assertTrue(ticket_creation_requested('Да', [dict(role='assistant', content='Хотите создать тикет?')]))

    def test_creation_does_not_trust_model_written_uuid(self):
        import os
        from unittest.mock import patch
        from src import email_poller as poller
        from test_email_poller import ENV
        response = dict(status='completed', output=[dict(type='message', role='assistant',
            content=[dict(type='output_text', text='Тикет 24d8d607-f9ae-401d-90db-e7f27982e16d успешно создан.')])])
        with patch.dict(os.environ, ENV), patch.object(poller, 'request_json', return_value=response) as request:
            result = poller.agent_answer('Создай тикет категории bug', 'fake', 'test@example.org', [])
        self.assertIsNone(result['ticket_id'])
        self.assertIn('не подтверждено', result['text'])
        self.assertNotIn('24d8d607', result['text'])
        self.assertEqual(request.call_args.kwargs['data']['tool_choice']['name'], 'create-ticket')

    def test_rag_question_requires_search(self):
        import os
        from unittest.mock import patch
        from src import email_poller as poller
        from test_email_poller import ENV
        response = dict(status='completed', output=[dict(type='message', role='assistant',
            content=[dict(type='output_text', text='Придуманная инструкция')])])
        with patch.dict(os.environ, ENV), patch.object(poller, 'request_json', return_value=response) as request:
            result = poller.agent_answer('Принтер не печатает, что делать?', 'fake', 'test@example.org', [])
        self.assertEqual(request.call_args.kwargs['data']['tool_choice'], {'type': 'file_search'})
        self.assertNotIn('Придуманная', result['text'])

    def test_old_assistant_answers_are_untrusted_context(self):
        import json
        import os
        from unittest.mock import patch
        from src import email_poller as poller
        from test_email_poller import ENV
        history = [dict(role='assistant', content='Старый неверный ответ')]
        response = dict(status='completed', output=[dict(type='message', role='assistant',
            content=[dict(type='output_text', text='Ответ')])])
        with patch.dict(os.environ, ENV), patch.object(poller, 'request_json', return_value=response) as request:
            poller.agent_answer('Принтер не печатает', 'fake', 'test@example.org', history)
        payload = request.call_args.kwargs['data']
        self.assertEqual([x['role'] for x in payload['input']], ['user'])
        context = json.loads(payload['input'][0]['content'])
        self.assertEqual(context['conversation_history'], history)
        self.assertEqual(context['message'], 'Принтер не печатает')
