#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${HELPDESK_MAILBOX:?Set HELPDESK_MAILBOX to the help desk address}"
: "${EMAIL_CREDENTIALS_SECRET_ID:?Set EMAIL_CREDENTIALS_SECRET_ID}"
: "${EMAIL_CREDENTIALS_SECRET_VERSION_ID:?Set EMAIL_CREDENTIALS_SECRET_VERSION_ID}"
: "${MCP_SERVER_URL:?Set MCP_SERVER_URL}"
: "${SEARCH_INDEX_ID:?Set SEARCH_INDEX_ID after the index is ready}"
: "${YDB_ENDPOINT_SECRET_ID:?Set YDB_ENDPOINT_SECRET_ID}"
: "${YDB_ENDPOINT_SECRET_VERSION_ID:?Set YDB_ENDPOINT_SECRET_VERSION_ID}"
: "${YDB_DATABASE_SECRET_ID:?Set YDB_DATABASE_SECRET_ID}"
: "${YDB_DATABASE_SECRET_VERSION_ID:?Set YDB_DATABASE_SECRET_VERSION_ID}"
SA_ID=$(yc iam service-account get --name ai-studio-sa --format json | jq -er .id)
FOLDER_ID=$(yc config get folder-id)
ARCHIVE=$(mktemp /tmp/email-poller.XXXXXXXX.zip)
trap 'rm -f "$ARCHIVE"' EXIT
python3.12 - "$ARCHIVE" <<'PY'
import sys
import zipfile
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write("src/email_poller.py", "email_poller.py")
    archive.write("src/helpdesk_common.py", "helpdesk_common.py")
    archive.write("src/rag.py", "rag.py")
    archive.write("src/guardrails.py", "guardrails.py")
    archive.write("src/knowledge_sources.json", "knowledge_sources.json")
    archive.write("src/requirements-poller.txt", "requirements.txt")
    archive.write("prompts/help-desk-system.md", "help-desk-system.md")
PY
# Create the function once before running this script:
# yc serverless function create --name email-poller
yc serverless function version create \
  --function-name email-poller \
  --runtime python312 \
  --entrypoint email_poller.handle \
  --memory 256m \
  --execution-timeout 120s \
  --source-path "$ARCHIVE" \
  --service-account-id "$SA_ID" \
  --environment "YC_FOLDER_ID=$FOLDER_ID,IMAP_HOST=imap.yandex.ru,IMAP_USER=$HELPDESK_MAILBOX,SMTP_HOST=smtp.yandex.ru,SMTP_PORT=465,SMTP_USER=$HELPDESK_MAILBOX,HELPDESK_MAILBOX=$HELPDESK_MAILBOX,MCP_SERVER_URL=$MCP_SERVER_URL,SEARCH_INDEX_ID=$SEARCH_INDEX_ID,RAG_SCORE_THRESHOLD=${RAG_SCORE_THRESHOLD:-0.35},GUARDRAIL_FAIL_OPEN=${GUARDRAIL_FAIL_OPEN:-true}" \
  --secret "environment-variable=IMAP_PASSWORD,id=$EMAIL_CREDENTIALS_SECRET_ID,version-id=$EMAIL_CREDENTIALS_SECRET_VERSION_ID,key=password" \
  --secret "environment-variable=SMTP_PASSWORD,id=$EMAIL_CREDENTIALS_SECRET_ID,version-id=$EMAIL_CREDENTIALS_SECRET_VERSION_ID,key=password" \
  --secret "environment-variable=YDB_ENDPOINT,id=$YDB_ENDPOINT_SECRET_ID,version-id=$YDB_ENDPOINT_SECRET_VERSION_ID,key=value" \
  --secret "environment-variable=YDB_DATABASE,id=$YDB_DATABASE_SECRET_ID,version-id=$YDB_DATABASE_SECRET_VERSION_ID,key=value"
