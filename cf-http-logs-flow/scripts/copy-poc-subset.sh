#!/usr/bin/env bash
# Copy the 20 PoC objects into s3://do-cf-logs/logs-poc/ (refreshes mtime for s3poll lookback).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIST="${ROOT}/poc-subset-20261110.txt"
BUCKET="${BUCKET_NAME:-do-cf-logs}"
SRC_PREFIX="${SRC_PREFIX:-logs/20261110}"
DST_PREFIX="${DST_PREFIX:-logs-poc}"
REGION="${AWS_REGION:-us-west-2}"

test -f "$LIST" || { echo "missing $LIST"; exit 1; }
echo "Copying $(wc -l < "$LIST" | tr -d ' ') objects -> s3://${BUCKET}/${DST_PREFIX}/"
while IFS= read -r key; do
  [ -z "$key" ] && continue
  echo "  $key"
  aws s3 cp "s3://${BUCKET}/${SRC_PREFIX}/${key}" "s3://${BUCKET}/${DST_PREFIX}/${key}" --region "$REGION"
done < "$LIST"
echo "Done. List:"
aws s3 ls "s3://${BUCKET}/${DST_PREFIX}/" --region "$REGION"
