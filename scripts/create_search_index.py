"""Upload only the eight demo knowledge documents using the official CLI."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    env_file = ROOT / ".env"
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    if any(line.startswith("SEARCH_INDEX_ID=") and line.partition("=")[2].strip()
           for line in lines) or os.environ.get("SEARCH_INDEX_ID", "").strip():
        raise SystemExit("SEARCH_INDEX_ID is already configured; no duplicate index created")
    cli = Path(sys.executable).with_name("yandex-ai-studio")
    if not cli.exists():
        raise SystemExit("Install requirements-rag.txt into .venv first")
    yc = shutil.which("yc") or str(ROOT.parent / ".tools/yc/bin/yc")
    folder = subprocess.check_output([yc, "config", "get", "folder-id"], text=True).strip()
    token = subprocess.check_output([yc, "iam", "create-token"], text=True).strip()
    env = {**os.environ, "YC_FOLDER_ID": folder, "YC_IAM_TOKEN": token}
    # An inherited API key would override the selected IAM token in the SDK.
    env.pop("YC_API_KEY", None)
    catalog = json.loads((ROOT / "src/knowledge_sources.json").read_text())
    files = [ROOT / "knowledge-base" / name for name in sorted(catalog)]
    if not 5 <= len(files) <= 10 or not all(path.is_file() for path in files):
        raise SystemExit("Expected 5–10 existing knowledge documents from the source catalog")
    command = [str(cli), "vector-stores", "local", *map(str, files),
               "--folder-id", folder, "--name", "help-desk-kb", "--format", "json",
               "--poll-timeout", "600"]
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    if result.returncode:
        # No token is present in argv; CLI diagnostics remain in the local terminal.
        raise SystemExit(result.stderr or result.stdout)
    payload = json.loads(result.stdout)
    if payload.get("status") != "success" or not payload.get("search_index", {}).get("id"):
        raise SystemExit("CLI did not confirm index readiness; .env was not changed")
    index_id = payload["search_index"]["id"]
    lines = [line for line in lines if not line.startswith("SEARCH_INDEX_ID=")]
    lines.append("SEARCH_INDEX_ID=" + index_id)
    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    manifest = {"index_id": index_id, "name": "help-desk-kb", "folder_id": folder,
                "files": [{"filename": path.name,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                          for path in files]}
    (evidence / "rag-index.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Ready search index:", index_id, "— ID saved in .env")


if __name__ == "__main__":
    main()
