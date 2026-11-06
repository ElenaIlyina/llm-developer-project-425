import json
import os
import smtplib
import unittest
from unittest.mock import patch
from src import email_sender

ENV = {"HELPDESK_MAILBOX": "desk@example.org", "OPERATOR_EMAIL": "operator@example.org",
       "SMTP_USER": "desk@example.org", "SMTP_PASSWORD": "test-only"}


class SenderTests(unittest.TestCase):
    @patch.dict(os.environ, ENV)
    @patch.object(email_sender.smtplib, "SMTP_SSL")
    def test_fixed_recipient(self, smtp):
        result = email_sender.handle({"httpMethod": "POST", "body": json.dumps(
            {"subject": "Дайджест", "body": "Открытые заявки"})}, None)
        self.assertEqual(result["statusCode"], 200)
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(message["To"], ENV["OPERATOR_EMAIL"])

    @patch.object(email_sender.smtplib, "SMTP_SSL")
    def test_recipient_override_rejected(self, smtp):
        result = email_sender.handle({"httpMethod": "POST", "body": json.dumps(
            {"subject": "Test", "body": "Text", "to": "someone@example.org"})}, None)
        self.assertEqual(result["statusCode"], 400)
        smtp.assert_not_called()

    @patch.dict(os.environ, ENV)
    @patch.object(email_sender.smtplib, "SMTP_SSL")
    def test_temporary_smtp_error_is_retryable(self, smtp):
        smtp.side_effect = OSError("Unavailable")
        result = email_sender.handle({"httpMethod": "POST", "body": json.dumps(
            {"subject": "Test", "body": "Text"})}, None)
        self.assertEqual(result["statusCode"], 503)

    @patch.object(email_sender.smtplib, "SMTP_SSL")
    def test_header_injection_rejected(self, smtp):
        result = email_sender.handle({"httpMethod": "POST", "body": json.dumps(
            {"subject": "Test\nBcc: other@example.org", "body": "Text"})}, None)
        self.assertEqual(result["statusCode"], 400)
        smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
