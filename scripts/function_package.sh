# Sourced by deployment scripts. Temporary build objects contain code/wheels, never secrets.
prepare_function_package() {
  .venv/bin/python scripts/package_function.py "$1" "$ARCHIVE"
  PACKAGE_ARGS=(--source-path "$ARCHIVE")
  PACKAGE_BUCKET=""
  if [ "$(wc -c < "$ARCHIVE")" -gt 3500000 ]; then
    PACKAGE_BUCKET="helpdesk-build-$(python3.12 -c 'import uuid; print(uuid.uuid4().hex[:16])')"
    yc storage bucket create --name "$PACKAGE_BUCKET" --max-size 104857600 >/dev/null
    yc storage s3 cp "$ARCHIVE" "s3://$PACKAGE_BUCKET/function.zip" \
      --grants "read=id=$SA_ID" --only-show-errors
    PACKAGE_ARGS=(--package-bucket-name "$PACKAGE_BUCKET" --package-object-name function.zip)
  fi
}

cleanup_function_package() {
  rm -f "$ARCHIVE"
  if [ -n "${PACKAGE_BUCKET:-}" ]; then
    # Delete only this invocation's unique temporary object and bucket.
    yc storage s3 rm "s3://$PACKAGE_BUCKET/function.zip" --only-show-errors \
      && yc storage bucket delete --name "$PACKAGE_BUCKET" >/dev/null \
      || echo "Temporary build bucket needs cleanup: $PACKAGE_BUCKET" >&2
  fi
}
