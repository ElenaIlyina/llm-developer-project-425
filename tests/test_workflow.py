import json
from pathlib import Path
import subprocess
import unittest
import jsonschema
from scripts.render_workflow import build_workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.spec = build_workflow(
            {"type": "YDB", "host": "example.org", "port": 2135,
             "database": "/test", "ssl": True, "iam": True},
            "gpt://test-folder/yandexgpt/latest", "https://example.org/sender",
        )

    def test_valid_against_official_schema(self):
        schema = json.loads(Path("schemas/yawl.json").read_text())
        jsonschema.Draft4Validator(schema).validate(self.spec)

    def test_digest_uses_foundation_models_response(self):
        step = self.spec["steps"]["compose_digest"]["foundationModelsCall"]
        raw = {"alternatives": [{"message": {"text": "Тестовый дайджест"}}],
               "usage": {"inputTextTokens": "10", "completionTokens": "5"}}
        result = json.loads(subprocess.check_output(
            ["jq", step["output"][2:-2]], input=json.dumps(raw), text=True))
        self.assertEqual(result["digest"], "Тестовый дайджест")
        self.assertEqual(result["model_usage"], raw["usage"])

    def test_updates_only_selected_ids(self):
        template = self.spec["steps"]["mark_escalated"]["databaseQuery"]["query"]
        query = subprocess.check_output(
            ["jq", "-r", template[2:-2]],
            input=json.dumps({"tickets": [{"id": "ticket-one"}, {"id": "ticket-two"}]}),
            text=True,
        )
        self.assertIn('id IN ("ticket-one","ticket-two")', query)
        self.assertIn('status = "open"', query)

    def test_permission_errors_not_retried(self):
        for step in self.spec["steps"].values():
            for body in step.values():
                if isinstance(body, dict):
                    errors = body.get("retryPolicy", {}).get("errorList", [])
                    self.assertNotIn("ALL", errors)
                    self.assertNotIn("STEP_PERMISSION_DENIED", errors)
                    # The service also uses this code for PermissionDenied on discovery.
                    self.assertNotIn("DATABASE_QUERY_CONNECTION_FAILED", errors)

    def test_delivery_failure_has_compensation(self):
        catch = self.spec["steps"]["send_digest"]["httpCall"]["catch"][0]
        self.assertEqual(catch["next"], "restore_open")
        self.assertEqual(
            self.spec["steps"]["restore_open"]["databaseQuery"]["next"], "delivery_failed")


if __name__ == "__main__":
    unittest.main()
