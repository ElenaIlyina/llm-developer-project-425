import json
import unittest
from unittest.mock import MagicMock, patch
from src.helpdesk_common import mask_pii
from src.ydb_tickets import index
from src import email_poller as poller
from test_email_poller import incoming, ENV
import os


class TicketTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(index, "classify_text", return_value="safe")
        guard.start()
        self.addCleanup(guard.stop)

    @patch.object(index, "get_store")
    def test_mcp_direct_arguments_create_ticket(self, store):
        store.return_value.create_ticket.return_value = {"ticket_id": "id"}
        result = index.handle({"user_id": "employee@example.org",
                               "category": "bug", "text": "Принтер сломан"}, None)
        self.assertEqual(result, {"ticket_id": "id"})
        store.return_value.create_ticket.assert_called_once_with(
            "employee@example.org", "bug", "Принтер сломан")

    @patch.object(index, "get_store")
    def test_direct_and_http_list(self, store):
        store.return_value.list_tickets.return_value = []
        self.assertEqual(index.handle({"action": "list-my-tickets",
                                       "user_id": "employee@example.org"}, None), [])
        response = index.handle({"httpMethod": "POST", "body": json.dumps(
            {"user_id": "employee@example.org"})}, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), [])

    @patch.object(index, "get_store")
    def test_invalid_category_never_touches_database(self, store):
        with self.assertRaises(ValueError):
            index.handle({"user_id": "employee@example.org",
                          "category": "bad", "text": "Problem"}, None)
        store.assert_not_called()

    def test_masking(self):
        self.assertEqual(mask_pii("email a@b.ru +7 999 123-45-67 token=abc"),
                         "email [email] +7 (***) ***-**-67 token=[SECRET]")


class HistoryTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(poller, "classify_text", return_value="safe")
        guard.start()
        self.addCleanup(guard.stop)

    @patch.dict(os.environ, ENV)
    @patch.object(poller, "send_reply")
    @patch.object(poller, "agent_answer")
    @patch.object(poller, "get_store")
    def test_history_and_real_metrics_link_both_messages(self, factory, agent, send):
        store = factory.return_value
        history = [{"role": "assistant", "content": "Чем помочь?"}]
        store.history.return_value = history
        ticket = "4cdb02d5-10f1-43d0-a28c-4103fd05c9dc"
        agent.return_value = {"text": "Заявка создана", "ticket_id": ticket,
                              "model": "test-model", "tokens_in": 11,
                              "tokens_out": 12, "latency_ms": 123}
        poller.process_message(incoming(), "employee@example.org", "fake", "uid-1")
        agent.assert_called_once_with("Привет", "fake", "employee@example.org", history)
        saves = store.save_message.call_args_list
        self.assertEqual([call.args[2] for call in saves], ["user", "agent"])
        self.assertEqual(saves[1].kwargs["tokens_in"], 11)
        self.assertEqual(saves[1].kwargs["latency_ms"], 123)
        store.link_ticket.assert_called_once_with(
            "employee@example.org", [saves[0].args[0], saves[1].args[0]], ticket)
        send.assert_called_once()

    def test_ticket_id_from_nested_mcp_result(self):
        value = json.dumps({"content": [{"type": "text", "text":
                           json.dumps({"ticket_id": "abc"})}]})
        self.assertEqual(poller.parse_tool_output(value), "abc")
        self.assertIsNone(poller.parse_tool_output("invalid json"))


if __name__ == "__main__":
    unittest.main()
