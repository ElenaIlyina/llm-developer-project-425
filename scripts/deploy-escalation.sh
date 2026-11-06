#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OPERATOR_EMAIL:?Set OPERATOR_EMAIL}"
: "${HELPDESK_MAILBOX:?Set HELPDESK_MAILBOX}"
: "${EMAIL_CREDENTIALS_SECRET_ID:?Set EMAIL_CREDENTIALS_SECRET_ID}"
: "${EMAIL_CREDENTIALS_SECRET_VERSION_ID:?Set EMAIL_CREDENTIALS_SECRET_VERSION_ID}"
SA_ID=$(yc iam service-account get --name ai-studio-sa --format json | jq -er .id)
FOLDER_ID=$(yc config get folder-id)
ARCHIVE=$(mktemp /tmp/email-sender.XXXXXXXX.zip)
trap 'rm -f "$ARCHIVE"' EXIT
python3.12 - "$ARCHIVE" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write("src/email_sender.py", "email_sender.py")
PY
# Create email-sender once before running this script if absent.
yc serverless function version create \
  --function-name email-sender --runtime python312 \
  --entrypoint email_sender.handle --memory 128m --execution-timeout 30s \
  --source-path "$ARCHIVE" --service-account-id "$SA_ID" \
  --environment "HELPDESK_MAILBOX=$HELPDESK_MAILBOX,OPERATOR_EMAIL=$OPERATOR_EMAIL,SMTP_HOST=smtp.yandex.ru,SMTP_PORT=465,SMTP_USER=$HELPDESK_MAILBOX" \
  --secret "environment-variable=SMTP_PASSWORD,id=$EMAIL_CREDENTIALS_SECRET_ID,version-id=$EMAIL_CREDENTIALS_SECRET_VERSION_ID,key=password"
# HTTPCall has no automatic IAM auth; the function accepts only the fixed recipient.
yc serverless function allow-unauthenticated-invoke email-sender
.venv/bin/python scripts/render_workflow.py
# daily-escalation is created in this workspace; for a new installation use workflow create.
yc serverless workflow update \
  --name daily-escalation --yaml-spec src/workflow.yaml \
  --service-account-id "$SA_ID" --log-folder-id "$FOLDER_ID"
for ROLE in serverless.workflows.executor serverless.workflows.viewer; do
  yc serverless workflow add-access-binding \
    --name daily-escalation --role "$ROLE" --service-account-id "$SA_ID"
done
echo "Deployed without adding a schedule. Validate delivery before enabling the daily schedule."
