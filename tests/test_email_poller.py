import email
from email import policy
from email.message import EmailMessage
import os
import unittest
from unittest.mock import MagicMock, patch
from src import email_poller as poller

ENV = {
    "HELPDESK_MAILBOX": "helpdesk@example.org",
    "IMAP_USER": "helpdesk@example.org",
    "SMTP_USER": "helpdesk@example.org",
    "IMAP_PASSWORD": "test-only",
    "SMTP_PASSWORD": "test-only",
    "YC_FOLDER_ID": "test-folder",
    "MCP_SERVER_URL": "https://example.invalid/sse",
    "SEARCH_INDEX_ID": "test-index",
}


def incoming(text="Привет"):
    msg = EmailMessage()
    msg["From"] = "Employee <employee@example.org>"
    msg["Subject"] = "Тест"
    msg["Message-ID"] = "<test@example.org>"
    msg.set_content(text)
    return msg


class PollerTests(unittest.TestCase):
    def test_html_fallback_ignores_scripts(self):
        msg = EmailMessage()
        msg.set_content("<p>Вопрос</p><script>secret</script>", subtype="html")
        self.assertEqual(poller.message_text(msg), "Вопрос")

    @patch.dict(os.environ, ENV)
    def test_auto_mail_and_own_mail_are_skipped(self):
        msg = incoming()
        self.assertTrue(poller.skip_message(msg, ENV["IMAP_USER"]))
        msg["Auto-Submitted"] = "auto-replied"
        self.assertTrue(poller.skip_message(msg, "employee@example.org"))

    @patch.dict(os.environ, ENV)
    @patch("src.email_poller.smtplib.SMTP_SSL")
    def test_reply_keeps_thread(self, smtp):
        poller.send_reply(incoming(), "employee@example.org", "Здравствуйте")
        reply = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(reply["Subject"], "Re: Тест")
        self.assertEqual(reply["In-Reply-To"], "<test@example.org>")
        self.assertEqual(reply["Auto-Submitted"], "auto-replied")

    @patch.dict(os.environ, ENV)
    def test_response_extracts_final_text(self):
        payload = {"status": "completed", "output": [
            {"type": "reasoning"},
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "Ответ"}]},
        ]}
        with patch.object(poller.Path, "read_text", return_value="Instructions"), patch.object(
            poller, "request_json", return_value=payload
        ) as request:
            self.assertIn("поиск не выполнен", poller.agent_answer("Вопрос", "fake-token", "employee@example.org", [])["text"])
            self.assertEqual(request.call_args.kwargs["data"]["instructions"], "Instructions")
            self.assertNotIn("employee@example.org", request.call_args.kwargs["data"]["instructions"])
            self.assertEqual(request.call_args.kwargs["data"]["tools"][0]["require_approval"], "never")
            self.assertEqual(request.call_args.kwargs["data"]["tools"][0]["allowed_tools"], ["list-my-tickets"])
            self.assertNotIn("prompt", request.call_args.kwargs["data"])

    @patch.dict(os.environ, ENV)
    def test_failed_message_does_not_block_next(self):
        imap = MagicMock()
        imap.select.return_value = ("OK", [])
        def command(operation, *args):
            if operation == "search":
                return "OK", [b"1 2"]
            if operation == "fetch":
                return "OK", [(b"BODY", incoming().as_bytes())]
            return "OK", []
        imap.uid.side_effect = command
        with patch.object(poller, "connect_mailbox") as connection, patch.object(
            poller, "get_token", return_value="fake-token"
        ), patch.object(
            poller, "process_message", side_effect=[ValueError("unavailable"), None]
        ) as process:
            connection.return_value.__enter__.return_value = imap
            result = poller.handle({}, None)
        self.assertEqual(result, {"processed": 1, "failed": 1, "skipped": 0})
        self.assertEqual(process.call_count, 2)
        stores = [call for call in imap.uid.call_args_list if call.args[0] == "store"]
        self.assertEqual(len(stores), 2)
        self.assertEqual(stores[0].args[3], "(\\Seen)")


if __name__ == "__main__":
    unittest.main()
