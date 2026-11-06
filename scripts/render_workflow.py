"""Build and validate the daily escalation YaWL specification."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ReadableDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def represent_string(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|" if "\n" in value else None)


ReadableDumper.add_representer(str, represent_string)


def retry(codes):
    return {"errorList": codes, "errorListMode": "INCLUDE", "retryCount": 3,
            "initialDelay": "2s", "maxDelay": "15s", "backoffRate": 2}


def build_workflow(connection, model_url, sender_url):
    transient_db = retry(["STEP_TIMEOUT", "DATABASE_QUERY_UNAVAILABLE"])
    select = {
        "connection": connection,
        "query": """SELECT id, category, status, Unicode::Substring(text, 0, 500) AS text, created_at
FROM tickets
WHERE status = 'open'
  AND created_at < CurrentUtcTimestamp() - Interval('PT24H')
ORDER BY created_at LIMIT 20;""",
        "mode": "QUERY", "timeout": "30s", "retryPolicy": transient_db,
        "output": '{{ {"tickets": (.ResultSets[0] // [])} }}',
        "next": "check_overdue",
    }
    # Quote only the selected UUIDs as SQL string literals via jq @json.
    ids = '(.tickets | map(.id | @json) | join(","))'
    mark_query = '{{ "UPDATE tickets SET status = \\"escalated\\", updated_at = CurrentUtcTimestamp() WHERE status = \\"open\\" AND created_at < CurrentUtcTimestamp() - Interval(\\"PT24H\\") AND id IN (" + ' + ids + ' + ");" }}'
    rollback_query = '{{ "UPDATE tickets SET status = \\"open\\", updated_at = CurrentUtcTimestamp() WHERE status = \\"escalated\\" AND id IN (" + ' + ids + ' + ");" }}'
    return {
        "yawl": "0.1", "start": "select_overdue",
        "steps": {
            "select_overdue": {"databaseQuery": select},
            "check_overdue": {"switch": {"choices": [
                {"condition": "{{ (.tickets | length) > 0 }}", "next": "compose_digest"},
                {"condition": "true", "next": "done"},
            ]}},
            "compose_digest": {"foundationModelsCall": {
                "modelUrl": model_url,
                "generate": {
                    "temperature": 0,
                    "maxTokens": 2500,
                    "jsonObject": False,
                    "messages": {"messages": [
                        {"role": "system", "text": (ROOT / "prompts/daily-escalation.md").read_text(encoding="utf-8")},
                        {"role": "user", "text": '{{ .tickets | tojson }}'},
                    ]},
                },
                "timeout": "60s",
                "retryPolicy": retry(["STEP_TIMEOUT", "STEP_INTERNAL"]),
                "output": '{{ {"digest": .alternatives[0].message.text, "model_usage": .usage} }}',
                "next": "check_digest",
            }},
            "check_digest": {"switch": {"choices": [
                {"condition": '{{ (.digest | type) == "string" and (.digest | length) > 0 }}',
                 "next": "mark_escalated"},
                {"condition": "true", "next": "invalid_digest"},
            ]}},
            "mark_escalated": {"databaseQuery": {
                "connection": connection, "query": mark_query, "mode": "EXEC",
                "timeout": "30s", "retryPolicy": transient_db,
                "output": '{{ {"marked": true} }}', "next": "send_digest",
            }},
            "send_digest": {"httpCall": {
                "url": sender_url, "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": '{{ {"subject": "Help Desk: просроченные заявки", "body": .digest} | tojson }}',
                "timeout": "25s",
                "retryPolicy": retry(["STEP_TIMEOUT", "HTTP_CALL_502",
                                      "HTTP_CALL_503", "HTTP_CALL_504"]),
                "catch": [{"errorList": ["ALL"], "errorListMode": "INCLUDE",
                           "output": '{{ {"send_error": .} }}', "next": "restore_open"}],
                "output": '{{ {"sent": true} }}', "next": "done",
            }},
            "restore_open": {"databaseQuery": {
                "connection": connection, "query": rollback_query, "mode": "EXEC",
                "timeout": "30s", "retryPolicy": transient_db,
                "output": '{{ {"restored": true} }}', "next": "delivery_failed",
            }},
            "invalid_digest": {"fail": {"errorMessage": "AI returned an empty digest; tickets unchanged"}},
            "delivery_failed": {"fail": {"errorMessage": "Digest delivery failed; selected tickets restored to open"}},
            "done": {"success": {}},
        },
    }


def yc_json(*arguments):
    return json.loads(subprocess.check_output(["yc", *arguments, "--format", "json"], text=True))


def lockbox_value(secret_id):
    payload = yc_json("lockbox", "payload", "get", secret_id)
    return next(entry["text_value"] for entry in payload["entries"] if entry["key"] == "value")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="src/workflow.yaml")
    args = parser.parse_args()
    endpoint = urlparse(lockbox_value(os.environ["YDB_ENDPOINT_SECRET_ID"]))
    connection = {
        "type": "YDB", "host": endpoint.hostname, "port": endpoint.port or 2135,
        "database": lockbox_value(os.environ["YDB_DATABASE_SECRET_ID"]),
        "ssl": True, "iam": True,
    }
    sender_id = yc_json("serverless", "function", "get", "--name", "email-sender")["id"]
    folder_id = subprocess.check_output(["yc", "config", "get", "folder-id"], text=True).strip()
    spec = build_workflow(connection, f"gpt://{folder_id}/yandexgpt/latest",
                          "https://functions.yandexcloud.net/" + sender_id)
    schema = json.loads((ROOT / "schemas/yawl.json").read_text())
    jsonschema.Draft4Validator(schema).validate(spec)
    Path(args.output).write_text(yaml.dump(spec, Dumper=ReadableDumper, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    print("Validated and written:", args.output)


if __name__ == "__main__":
    main()
