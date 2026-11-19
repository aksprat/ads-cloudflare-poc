#!/usr/bin/env bash
# Download the 20 PoC objects locally (needs only s3:GetObject / read).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIST="${ROOT}/poc-subset-20261110.txt"
BUCKET="${BUCKET_NAME:-do-cf-logs}"
SRC_PREFIX="${SRC_PREFIX:-logs/20261110}"
REGION="${AWS_REGION:-us-west-2}"
OUT="${OUT_DIR:-${ROOT}/poc-objects}"

test -f "$LIST" || { echo "missing $LIST"; exit 1; }
mkdir -p "$OUT"
echo "Downloading $(wc -l < "$LIST" | tr -d ' ') objects -> $OUT"
while IFS= read -r key; do
  [ -z "$key" ] && continue
  echo "  $key"
  aws s3 cp "s3://${BUCKET}/${SRC_PREFIX}/${key}" "${OUT}/${key}" --region "$REGION"
done < "$LIST"
echo "Done. Local files:"
ls -lh "$OUT" | head -30
