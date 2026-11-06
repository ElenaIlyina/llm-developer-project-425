"""Run real model/search checks without sending email or creating tickets."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from email_poller import agent_answer


def validate_results(checks):
    assert all(result["searches"] for result in checks.values()), "Model skipped file_search"
    assert checks["known"]["sources"], "Known answer lacks verified file citations"
    assert "business-travel.md" in {s["filename"] for s in checks["known"]["sources"]}
    assert not any(result["ticket_id"] for result in checks.values()), "Unapproved ticket created"
    unknown = checks["unknown"]["text"].casefold()
    admits_missing_answer = any(phrase in unknown for phrase in
                               ("не знаю", "нет информации", "нет этой информации"))
    offers_ticket = any(word in unknown for word in ("тикет", "заявк"))
    assert admits_missing_answer and offers_ticket, "Review unknown-answer behavior"
    assert not checks["unknown"]["sources"], "Unknown answer has unrelated source links"


def main():
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)
    if not os.environ.get("SEARCH_INDEX_ID"):
        raise SystemExit("Create the search index first")
    yc = shutil.which("yc") or str(ROOT.parent / ".tools/yc/bin/yc")
    os.environ["YC_FOLDER_ID"] = subprocess.check_output(
        [yc, "config", "get", "folder-id"], text=True).strip()
    account = json.loads(subprocess.check_output(
        [yc, "iam", "service-account", "get", "--name", "ai-studio-sa", "--format", "json"],
        text=True))["id"]
    token = subprocess.check_output(
        [yc, "iam", "create-token", "--impersonate-service-account-id", account], text=True).strip()
    checks = {}
    for name, question in {
        "known": "Как оформить командировку по учебному регламенту?",
        "unknown": "Какова точная сумма учебной корпоративной компенсации за занятия скалолазанием?",
    }.items():
        result = agent_answer(question, token, "rag-check@example.invalid", [])
        checks[name] = {"question": question, **result}
        print(name, result["text"])
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "rag-checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n")
    validate_results(checks)
    print("Live RAG checks passed; evidence saved")


if __name__ == "__main__":
    main()
