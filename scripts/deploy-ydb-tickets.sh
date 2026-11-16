#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${YDB_ENDPOINT_SECRET_ID:?Set YDB_ENDPOINT_SECRET_ID}"
: "${YDB_ENDPOINT_SECRET_VERSION_ID:?Set YDB_ENDPOINT_SECRET_VERSION_ID}"
: "${YDB_DATABASE_SECRET_ID:?Set YDB_DATABASE_SECRET_ID}"
: "${YDB_DATABASE_SECRET_VERSION_ID:?Set YDB_DATABASE_SECRET_VERSION_ID}"
SA_ID=$(yc iam service-account get --name ai-studio-sa --format json | jq -er .id)
FOLDER_ID=$(yc config get folder-id)
ARCHIVE=$(mktemp /tmp/ydb-tickets.XXXXXXXX.zip)
source scripts/function_package.sh
trap cleanup_function_package EXIT
prepare_function_package tickets
yc serverless function version create \
  --function-name ydb-tickets \
  --runtime python312 --entrypoint index.handle \
  --memory 256m --execution-timeout 45s \
  "${PACKAGE_ARGS[@]}" --service-account-id "$SA_ID" \
  --environment "YC_FOLDER_ID=$FOLDER_ID,GUARDRAIL_FAIL_OPEN=${GUARDRAIL_FAIL_OPEN:-true}" \
  --secret "environment-variable=YDB_ENDPOINT,id=$YDB_ENDPOINT_SECRET_ID,version-id=$YDB_ENDPOINT_SECRET_VERSION_ID,key=value" \
  --secret "environment-variable=YDB_DATABASE,id=$YDB_DATABASE_SECRET_ID,version-id=$YDB_DATABASE_SECRET_VERSION_ID,key=value"
