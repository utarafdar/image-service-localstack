#!/usr/bin/env bash
set -euo pipefail

# Usage: ./client_upload_presign.sh <presigned_url> <image_file> [content_type]
URL="${1:-}"
FILE="${2:-}"
if [ -z "$URL" ] || [ -z "$FILE" ]; then
  echo "Usage: $0 <presigned_url> <image_file> [content_type]" >&2
  exit 2
fi

if [ ! -f "$FILE" ]; then
  echo "File not found: $FILE" >&2
  exit 3
fi

# If the presigned URL uses the container hostname "localstack", rewrite to localhost
# so the host (your machine) can resolve it.
# Also handle arbitrary hostnames by mapping them to localhost:4566.
URL="${URL/http:\/\/localstack:4566/http:\/\/localhost:4566}"
URL="$(echo "$URL" | sed -E 's#^https?://[^/]+#http://localhost:4566#')"

CONTENT_TYPE="${3:-$(file --brief --mime-type -- "$FILE" 2>/dev/null || echo 'application/octet-stream')}"

HTTP_CODE=$(curl --silent --show-error --write-out "%{http_code}" \
  -X PUT \
  -H "Content-Type: ${CONTENT_TYPE}" \
  --data-binary @"${FILE}" \
  "${URL}" -o /dev/null)

if [[ "$HTTP_CODE" =~ ^2[0-9][0-9]$ ]]; then
  echo "Upload succeeded (HTTP ${HTTP_CODE})"
  exit 0
else
  echo "Upload failed (HTTP ${HTTP_CODE})" >&2
  exit 4
fi