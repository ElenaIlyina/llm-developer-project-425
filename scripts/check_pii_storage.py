"""Read a test ticket, linked messages and logs; never modify cloud data."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from helpdesk_common import Store

MASKS = ("+7 (***) ***-**-12", "[email]", "****-****-****-****")


def raw_test_data_present(text):
    digits = re.sub(r"\D", "", text)
    return ("test@example.invalid" in text.casefold() or "4111111111111111" in digits
            or "9991234512" in digits)


def storage_checks(ticket_text, messages, boundary_text=None):
    user_messages = [message for message in messages if message.role == "user"]
    checks = {
        "user_messages_have_all_masks": bool(user_messages) and all(
            all(mask in message.text for mask in MASKS) for message in user_messages),
        "ticket_has_no_raw_test_data": not raw_test_data_present(ticket_text),
        "messages_have_no_raw_test_data": all(not raw_test_data_present(m.text) for m in messages),
        "both_roles_linked": {message.role for message in messages} == {"user", "agent"},
    }
    if boundary_text is not None:
        checks["direct_ticket_has_all_masks"] = all(mask in boundary_text for mask in MASKS)
        checks["direct_ticket_has_no_raw_test_data"] = not raw_test_data_present(boundary_text)
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticket_id")
    parser.add_argument("--boundary-ticket-id", help="Ticket created by direct invoke with raw test PII")
    args = parser.parse_args()
    config = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                  if "=" in line and not line.startswith("#"))
    yc = shutil.which("yc") or str(ROOT.parent / ".tools/yc/bin/yc")
    for key in ("YDB_ENDPOINT", "YDB_DATABASE"):
        payload = json.loads(subprocess.check_output(
            [yc, "lockbox", "payload", "get", config[key + "_SECRET_ID"], "--format", "json"],
            text=True))
        os.environ[key] = next(e["text_value"] for e in payload["entries"] if e["key"] == "value")
    os.environ["YC_IAM_TOKEN"] = subprocess.check_output([yc, "iam", "create-token"], text=True).strip()
    store = Store()
    tickets = store.execute("""
        DECLARE $id AS Utf8;
        SELECT id,user_id,category,status,text FROM tickets WHERE id=$id;
    """, {"$id": args.ticket_id})[0].rows
    if len(tickets) != 1:
        raise SystemExit("Expected exactly one ticket")
    ticket = tickets[0]
    messages = store.execute("""
        DECLARE $user AS Utf8;
        DECLARE $ticket AS Utf8;
        SELECT role,text FROM messages
        WHERE user_id=$user AND ticket_id=$ticket;
    """, {"$user": ticket.user_id, "$ticket": ticket.id})[0].rows
    ticket_safe = not raw_test_data_present(ticket.text)
    boundary_text = None
    if args.boundary_ticket_id:
        boundary = store.execute("""
            DECLARE $id AS Utf8;
            SELECT text FROM tickets WHERE id=$id;
        """, {"$id": args.boundary_ticket_id})[0].rows
        if len(boundary) != 1:
            raise SystemExit("Expected one direct-write boundary test ticket")
        boundary_text = boundary[0].text
    checks = storage_checks(ticket.text, messages, boundary_text)
    # If storage is faulty, do not repeat the leaked values in stdout or evidence.
    result = {
        "ticket": {"id": ticket.id, "category": ticket.category, "status": ticket.status,
                   "text": ticket.text if ticket_safe else "[REDACTED: raw test data found]"},
        "messages": [{"role": m.role,
                      "text": m.text if not raw_test_data_present(m.text) else "[REDACTED: raw test data found]"}
                     for m in messages],
        "storage_checks": checks, "logs": {},
        "ticket_boundary_checked": boundary_text is not None,
    }
    if boundary_text is not None:
        result["direct_ticket"] = {
            "id": args.boundary_ticket_id,
            "text": boundary_text if not raw_test_data_present(boundary_text)
            else "[REDACTED: raw test data found]",
        }
    for function in ("ydb-tickets", "email-poller"):
        try:
            log = subprocess.run([yc, "serverless", "function", "logs", function, "--since", "30m"],
                                 capture_output=True, text=True, timeout=20)
            if log.returncode:
                result["logs"][function] = {"available": False}
            else:
                result["logs"][function] = {
                    "available": True, "empty": not bool(log.stdout.strip()),
                    "raw_test_data_found": raw_test_data_present(log.stdout),
                }
        except subprocess.TimeoutExpired:
            result["logs"][function] = {"available": False, "timeout": True}
    result["storage_passed"] = all(checks.values())
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "pii-storage-check.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert result["storage_passed"], "Storage check failed; inspect redacted evidence"
    if boundary_text is None:
        print("Mail storage passed. Direct ticket-write masking still needs --boundary-ticket-id.")
    if not all(item.get("available") and not item.get("empty") for item in result["logs"].values()):
        print("Storage passed. Logs unavailable or empty: review Cloud Logging in the console separately.")
    else:
        assert not any(item.get("raw_test_data_found") for item in result["logs"].values()), "Raw test PII found in logs"
        print("Storage and log checks passed")


if __name__ == "__main__":
    main()
