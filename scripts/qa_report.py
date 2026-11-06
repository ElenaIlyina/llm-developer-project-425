"""Read a bounded, redacted YDB export and estimate a documented monthly scenario."""
import argparse
import json
import math
import os
import sys

try:
    from scripts.qa_common import ROOT, configure_cloud
    from scripts.qa_metrics import generation_cost, summarize
except ModuleNotFoundError:
    from qa_common import ROOT, configure_cloud
    from qa_metrics import generation_cost, summarize

sys.path.insert(0, str(ROOT / "src"))
from helpdesk_common import get_store, mask_pii, timestamp_text


def monthly_estimate(summary, rates, *, messages=300, days=30,
                     ticket_fraction=0.25, classifier_tokens=1000):
    count = summary["generation_responses"]
    if not count:
        raise ValueError("No measured generation responses to estimate")
    avg_in, avg_out = summary["tokens_in"] / count, summary["tokens_out"] / count
    # One classifier call per message, one more for a create-ticket action.
    classifications = messages * (1 + ticket_fraction)
    polling_calls = days * 24 * 60
    # Scenario assumptions, not measured function wall times: empty 1s, busy 10s.
    busy_calls = min(messages, polling_calls)
    gb_hours = (0.25 * (polling_calls - busy_calls + busy_calls * 10)
                + messages * ticket_fraction * 0.25 * 3 + days * 0.125) / 3600
    function_calls = polling_calls + messages * ticket_fraction + days
    gross_functions = gb_hours * rates["functions_per_gib_hour"] + (
        function_calls / 1_000_000 * rates["functions_per_million_calls"])
    with_allowance = max(0, gb_hours - rates["functions_free_gib_hours"]) * rates["functions_per_gib_hour"] + (
        max(0, function_calls - rates["functions_free_calls"]) / 1_000_000
        * rates["functions_per_million_calls"])
    components = {
        "generation": generation_cost(str(avg_in * messages), str(avg_out * messages),
                                      rates["generation_input_per_1000"], rates["generation_output_per_1000"]),
        "file_search": messages / 1000 * rates["file_search_per_1000_calls"],
        "classifier": classifications * max(1, math.ceil(classifier_tokens / 1000))
        * rates["classifier_lite_per_started_1000"],
        "index_storage": days * rates["index_per_rounded_gib_day"],
        "three_secret_versions": 3 * days * 24 * rates["secret_version_per_hour"],
    }
    return {
        "assumptions": {"messages": messages, "days": days, "ticket_fraction": ticket_fraction,
                        "one_search_per_message": True, "classifier_tokens_per_call": classifier_tokens,
                        "index_billed_gib": 1, "secret_versions": 3,
                        "empty_poller_seconds": 1, "busy_poller_seconds": 10,
                        "daily_digest_generation_not_included": True},
        "poller_calls": polling_calls,
        "known_components_rub": {k: round(v, 4) for k, v in components.items()},
        "functions_rub_if_allowance_available": round(with_allowance, 4),
        "functions_rub_if_allowance_exhausted": round(gross_functions, 4),
        "known_subtotal_with_available_allowance_rub": round(sum(components.values()) + with_allowance, 4),
        "known_subtotal_with_exhausted_allowance_rub": round(sum(components.values()) + gross_functions, 4),
        "excluded": ["tool tokens absent from historical YDB rows", "YDB RU and storage", "Lockbox payload reads", "network egress", "Cloud Logging",
                     "daily digest model tokens", "one-time indexing", "retries and additional tool calls"],
        "is_total_invoice": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", help="Default: OPERATOR_EMAIL; only this user's records are exported")
    parser.add_argument("--monthly-messages", type=int, default=300)
    args = parser.parse_args()
    if args.monthly_messages <= 0:
        raise SystemExit("--monthly-messages must be positive")
    configure_cloud()
    user = args.user_id or os.environ.get("OPERATOR_EMAIL")
    if not user:
        raise SystemExit("Set --user-id or OPERATOR_EMAIL")
    store = get_store()
    rows = store.execute("""
        DECLARE $u AS Utf8;
        SELECT id,user_id,role,ticket_id,text,model,tokens_in,tokens_out,latency_ms,created_at
        FROM messages WHERE user_id=$u ORDER BY created_at DESC LIMIT 500;
    """, {"$u": user.casefold()})[0].rows
    messages = [{"id": r.id, "role": r.role, "ticket_id": r.ticket_id,
                 "text": mask_pii(r.text), "model": r.model, "tokens_in": r.tokens_in,
                 "tokens_out": r.tokens_out, "latency_ms": r.latency_ms,
                 "created_at": timestamp_text(r.created_at)} for r in reversed(rows)]
    tickets = [{**t, "text": mask_pii(t["text"])} for t in store.list_tickets(user.casefold())]
    summary = summarize(messages)
    rates = json.loads((ROOT / "config/pricing-2026-11-06.json").read_text())
    report = {"export_scope": "One requested user; latest 500 messages and 20 tickets; user_id omitted",
              "summary": summary, "messages": messages, "tickets": tickets,
              "historical_usage_compared_to_api": False,
              "historical_usage_note": "Cloud logs unavailable; exact API comparison is in qa-live.json",
              "monthly_scenario": monthly_estimate(summary, rates, messages=args.monthly_messages),
              "rates": rates}
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "qa-token-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"summary": summary, "monthly_scenario": report["monthly_scenario"]},
                     ensure_ascii=False, indent=2))
    print("Redacted export saved to docs/evidence/qa-token-report.json")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("QA report failed: " + type(exc).__name__) from None
