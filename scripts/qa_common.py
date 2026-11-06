"""Local QA setup; credentials stay in the current process only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def configure_cloud():
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)
    yc = shutil.which("yc") or str(ROOT.parent / ".tools/yc/bin/yc")
    def command(*args):
        return subprocess.check_output([yc, *args], text=True, stderr=subprocess.PIPE).strip()
    os.environ["YC_FOLDER_ID"] = command("config", "get", "folder-id")
    for key in ("YDB_ENDPOINT", "YDB_DATABASE"):
        payload = json.loads(command("lockbox", "payload", "get",
                                     os.environ[key + "_SECRET_ID"], "--format", "json"))
        os.environ[key] = next(e["text_value"] for e in payload["entries"] if e["key"] == "value")
    os.environ["YC_IAM_TOKEN"] = command("iam", "create-token")
    account = json.loads(command("iam", "service-account", "get", "--name",
                                 "ai-studio-sa", "--format", "json"))["id"]
    api_token = command("iam", "create-token", "--impersonate-service-account-id", account)
    return api_token
