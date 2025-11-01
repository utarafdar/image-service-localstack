#!/usr/bin/env bash
set -euo pipefail

LAMBDA_NAME="upload_images"
TMP_ZIP="/tmp/${LAMBDA_NAME}.zip"
LOCALSTACK_CONTAINER="localstack-image-svc"
LOCALSTACK_SERVICE="localstack"

# Clean and create new zip
rm -f "${TMP_ZIP}"

echo "Cleaning Python caches..."
find src -name "__pycache__" -type d -exec rm -rf {} + >/dev/null 2>&1

cd src
zip -r "${TMP_ZIP}" lambdas/upload_images common -x "*.pyc" "__pycache__/*" >/dev/null
cd ..

# Update lambda code
docker compose exec -T ${LOCALSTACK_SERVICE} awslocal lambda update-function-code \
    --function-name ${LAMBDA_NAME} \
    --zip-file fileb:///tmp/${LAMBDA_NAME}.zip

echo "Lambda code updated successfully"
