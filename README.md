# Image Service (LocalStack) — README

Overview
--------
This repository implements a small image service (Instagram-like) using AWS primitives (API Gateway, Lambda, S3, DynamoDB, SQS) running locally with LocalStack. It provides APIs to:
- Upload image (presigned PUT URL)
- List user images (filters + pagination)
- View / download images (via presigned GET URLs returned by list)
- Delete image

Design highlights
-----------------
- Presigned S3 URLs: Lambdas never handle binary upload/download directly; clients upload/download to S3 using presigned URLs.
- DynamoDB stores image metadata and upload status (PENDING_UPLOAD / UPLOADED).
- S3 -> SQS -> Lambda: S3 object-created events delivered to SQS; a worker Lambda consumes SQS messages and marks DDB items as UPLOADED.
- Idempotent deploy script: scripts/deploy_localstack.sh creates or reuses resources so local development is repeatable.

What's implemented (src)
------------------------
- src/common/aws_clients.py
  - boto3_client(...) configured for LocalStack
  - deserialize_item(s) with Decimal -> int/float conversion

- src/lambdas/upload_images/handler.py
  - Generates presigned PUT URL, writes a DDB item with status="PENDING_UPLOAD" and s3_key.

- src/lambdas/list_images/handler.py
  - Query DDB for user images (filter by filename substring and/or content_type). Pagination (max 10). For items with status == "UPLOADED" returns S3 info and a presigned GET URL. For others returns metadata only.

- src/lambdas/delete_images/handler.py
  - Deletes DDB item and deletes S3 object only when status == "UPLOADED".

- src/lambdas/s3_listener/handler.py
  - Triggered via SQS (S3 notifications forwarded to SQS). Parses S3 key and updates DDB status -> "UPLOADED".

LocalStack deployment
---------------------
Requirements on host:
- Docker & Docker Compose (or `docker compose`)
- jq (used by deploy scripts): sudo apt-get install -y jq

Start LocalStack:
- chmod +x ./scripts/start_localstack.sh
- ./scripts/start_localstack.sh

Deploy resources & lambdas:
- chmod +x ./scripts/deploy_localstack.sh
- ./scripts/deploy_localstack.sh

The deploy script performs (idempotent):
- create S3 bucket (ROOT_BUCKET)
- create DynamoDB table (ImagesMetadata)
- create/get REST API (image-service-api)
- create or update Lambda functions
- create SQS queue and set policy for S3 -> SQS
- configure S3 bucket notification to SQS
- create Lambda event-source-mapping (SQS -> s3_listener)

API base (example)
- After deploy script prints API_ID, base endpoint looks like:
  http://localhost:4566/restapis/{API_ID}/local/_user_request_/

Example calls
-------------
- Upload (get presigned PUT):
  curl -s -X POST "http://localhost:4566/restapis/${API_ID}/local/_user_request_/uploadImages" \
    -H "Content-Type: application/json" \
    -d '{"user_id":"alice","filename":"pic.png","content_type":"image/png"}' | jq .

- Upload image using signed url:
  ./scripts/client_upload_presign.sh <signed_url> <local/path/to/image>
  

- List:
  curl -s -G "http://localhost:4566/restapis/${API_ID}/local/_user_request_/listImages" \
    --data-urlencode "user_id=alice" \
    --data-urlencode "filename=pic" | jq .

- Delete:
  curl -s -X DELETE "http://localhost:4566/restapis/${API_ID}/local/_user_request_/deleteImages" \
    -H "Content-Type: application/json" \
    -d '{"user_id":"alice","image_id":"<id>"}' | jq .

Notes on "View/download"
------------------------
There is no separate Lambda to stream files. For downloading/viewing, clients use the presigned GET URL returned by listImages for UPLOADED items.

Unit tests
----------
All unit tests are in tests/unit (pytest). To run tests inside Docker (no host test tools required) see "Run tests in Docker" below.

Run tests in Docker (no host installs)
-------------------------------------
- docker compose -f docker-compose.test.yml up --build --abort-on-container-exit

OpenAPI and Postman
-------------------
- OpenAPI spec: docs/openapi/image_service_openapi.yaml (includes upload/list/delete docs)
- Example Postman collection: docs/examples/postman_collection.json

Further notes
-------------
- To update only lambda code: ./scripts/update_lambda.sh <lambda_name>
- If you see "Missing Authentication Token" when calling an API path: either method/path not created, or stage not deployed. Re-run deploy_localstack.sh which publishes a deployment.
- Decimal -> JSON issues: handled in common.deserialize_item (Decimal -> int/float).
