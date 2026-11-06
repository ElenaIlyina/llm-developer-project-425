"""Exact token comparison and a clearly scoped generation cost scenario."""
from decimal import Decimal


def compare_usage(usage, stored):
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        if key not in usage:
            raise ValueError("Missing API usage field: " + key)
    incoming, outgoing = int(usage["input_tokens"]), int(usage["output_tokens"])
    tools = int((usage.get("input_tokens_details") or {}).get("tool_tokens") or 0)
    return {
        "input_matches": incoming == stored["tokens_in"],
        "output_matches": outgoing == stored["tokens_out"],
        "total_consistent": incoming + outgoing + tools == int(usage["total_tokens"]),
        "nonzero_generation": incoming > 0 and outgoing > 0,
        "latency_recorded": stored["latency_ms"] > 0,
    }


def generation_cost(tokens_in, tokens_out, input_rate, output_rate):
    return float((Decimal(tokens_in) * Decimal(str(input_rate)) +
                  Decimal(tokens_out) * Decimal(str(output_rate))) / Decimal(1000))


def summarize(rows):
    generated = [r for r in rows if r["role"] == "agent" and
                 (r.get("model") or "").startswith("gpt://")]
    return {
        "message_rows": len(rows), "generation_responses": len(generated),
        "guardrail_responses": sum(r["role"] == "agent" and
                                   (r.get("model") or "").startswith("guardrail/") for r in rows),
        "tokens_in": sum(r["tokens_in"] for r in generated),
        "tokens_out": sum(r["tokens_out"] for r in generated),
        "average_latency_ms": round(sum(r["latency_ms"] for r in generated) / len(generated), 2)
        if generated else None,
    }
