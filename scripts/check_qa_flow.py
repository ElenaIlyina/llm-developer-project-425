"""Real Responses/MCP/YDB QA, with SMTP replaced and test rows removed."""
import copy
from email.message import EmailMessage
import json
import os
import sys
import uuid
from unittest.mock import patch

try:
    from scripts.qa_common import ROOT, configure_cloud
    from scripts.qa_metrics import compare_usage
except ModuleNotFoundError:
    from qa_common import ROOT, configure_cloud
    from qa_metrics import compare_usage

sys.path.insert(0, str(ROOT / "src"))
import email_poller as poller
from helpdesk_common import get_store, mask_pii, timestamp_text


def redact(value):
    if isinstance(value, str):
        return mask_pii(value)
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: "[email]" if k in ("user_id", "sender_email", "email") else redact(v)
                for k, v in value.items()}
    return value


def response_trace(response):
    output = []
    for item in response.get("output", []):
        kind = item.get("type")
        summary = {"type": kind, "id": item.get("id")}
        if kind == "file_search_call":
            summary.update(poller.search_trace(item, mask_pii))
        elif kind == "mcp_call":
            summary.update({"name": item.get("name"), "server_label": item.get("server_label"),
                            "error": bool(item.get("error"))})
            for field in ("arguments", "output"):
                value = item.get(field)
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        pass
                summary[field] = redact(value)
        elif kind == "mcp_list_tools":
            summary["tool_names"] = [t.get("name") for t in item.get("tools", [])]
        elif kind == "message":
            summary["content"] = redact(item.get("content", []))
        output.append(summary)
    return {"response_id": response.get("id"), "model": response.get("model"),
            "usage": copy.deepcopy(response.get("usage", {})), "output": output}


def main():
    token = configure_cloud()
    os.environ["GUARDRAIL_FAIL_OPEN"] = "false"
    store = get_store()
    run = str(uuid.uuid4())
    user = "qa-" + run[:8] + "@example.invalid"
    captured = []
    original_request = poller.request_json
    def capture(*args, **kwargs):
        response = original_request(*args, **kwargs)
        if args[0].endswith("/responses"):
            captured.append(copy.deepcopy(response))
        return response
    report = {"run_id": run, "smtp_mocked": True, "turns": [], "passed": False}
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    previous = evidence / "qa-live.json"
    if previous.exists():
        prior = json.loads(previous.read_text())
        (evidence / ("qa-live-" + prior["run_id"] + ".json")).write_text(previous.read_text())
    try:
        with patch.object(poller, "request_json", side_effect=capture), patch.object(poller, "send_reply") as send:
            for number, text in enumerate(("У меня сломался принтер, что делать?",
                                           "Не помогло, создай тикет категории bug по проблеме принтера.")):
                source = "qa:" + run + ":" + str(number)
                message = EmailMessage()
                message.set_content(text)
                before = len(captured)
                poller.process_message(message, user, token, source)
                if len(captured) != before + 1:
                    raise AssertionError("Expected one primary Responses call per turn")
                agent_id = str(uuid.uuid5(uuid.NAMESPACE_URL, source + ":agent"))
                rows = store.execute("""
                    DECLARE $user AS Utf8; DECLARE $id AS Utf8;
                    SELECT id,ticket_id,role,text,model,tokens_in,tokens_out,latency_ms,created_at
                    FROM messages WHERE user_id=$user AND id=$id;
                """, {"$user": user, "$id": agent_id})[0].rows
                if len(rows) != 1:
                    raise AssertionError("Expected one saved agent message")
                row = rows[0]
                metrics = {"tokens_in": row.tokens_in, "tokens_out": row.tokens_out,
                           "latency_ms": row.latency_ms}
                comparison = compare_usage(captured[-1].get("usage", {}), metrics)
                report["turns"].append({"question": text, "message_id": agent_id,
                                       "reply": mask_pii(send.call_args.args[2]),
                                       "stored": metrics, "usage_comparison": comparison,
                                       "trace": response_trace(captured[-1])})
                if not all(comparison.values()):
                    raise AssertionError("Usage does not match YDB metrics: " + str(comparison))
        first = report["turns"][0]
        second = report["turns"][1]
        assert any(x["type"] == "file_search_call" for x in first["trace"]["output"])
        assert "printer.md" in first["reply"], "Printer answer has no source"
        assert any(x["type"] == "mcp_call" and x.get("name") == "create-ticket"
                   for x in second["trace"]["output"]), "No create-ticket call"
        tickets = store.list_tickets(user)
        assert len(tickets) == 1 and tickets[0]["category"] == "bug"
        report["ticket"] = redact(tickets[0])
        messages = store.execute("""
            DECLARE $user AS Utf8;
            SELECT id,role,ticket_id,text,model,tokens_in,tokens_out,latency_ms,created_at
            FROM messages WHERE user_id=$user ORDER BY created_at;
        """, {"$user": user})[0].rows
        report["messages"] = [
            {"id": r.id, "role": r.role, "ticket_id": r.ticket_id, "text": mask_pii(r.text),
             "model": r.model, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
             "latency_ms": r.latency_ms, "created_at": timestamp_text(r.created_at)}
            for r in messages]
        assert len(messages) == 4
        assert sum(r.ticket_id == tickets[0]["id"] for r in messages) == 2
        report["passed"] = True
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "detail": mask_pii(str(exc))}
        raise
    finally:
        # This random synthetic user belongs only to this run. Real users are untouched.
        try:
            store.execute("DECLARE $u AS Utf8; DELETE FROM messages WHERE user_id=$u;", {"$u": user})
            store.execute("DECLARE $u AS Utf8; DELETE FROM tickets WHERE user_id=$u;", {"$u": user})
            report["synthetic_rows_removed"] = True
        except Exception as exc:
            report["synthetic_rows_removed"] = False
            report["cleanup_error_type"] = type(exc).__name__
        (evidence / "qa-live.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    assert report.get("synthetic_rows_removed"), "Synthetic rows need cleanup; inspect report"
    print("Live QA passed: printer RAG, MCP ticket, 4 messages, exact usage match; test rows removed.")
    for number, turn in enumerate(report["turns"], 1):
        print("Turn", number, turn["stored"], turn["usage_comparison"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("Live QA failed: " + type(exc).__name__ + "; inspect docs/evidence/qa-live.json") from None
