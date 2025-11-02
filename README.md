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

Design Decisions
---------------
- Presigned S3 URLs: offloads large file transfer from Lambdas and backend, reduces cost and latency.
- DynamoDB metadata: simple, scalable NoSQL store for per-user image metadata.
- SQS between S3 and Lambda: reliable, decoupled processing of S3-created events (eventually consistent upload confirmation).
- Idempotent deploy script: creating resources only when missing makes local development repeatable.
- Small modular Lambdas: single responsibility functions, easier to test.

Project layout 
--------------------------------
- src/
  - common/aws_clients.py          — shared boto3 client creation + DynamoDB deserialization helpers
  - lambdas/
    - upload_images/handler.py     — returns presigned PUT URL; writes DDB item with status `PENDING_UPLOAD`
    - list_images/handler.py       — lists user's images (filters: filename substring, content_type); paginated; returns presigned GET only when status == `UPLOADED`
    - delete_images/handler.py     — deletes DDB item; deletes S3 object only when status == `UPLOADED`
    - s3_listener/handler.py       — triggered via SQS (S3 => SQS); reads S3 key, updates DDB item status -> `UPLOADED`
- scripts/
  - deploy_localstack.sh           — main idempotent deploy script (creates S3, DDB, API, Lambdas, SQS, bucket notification, event mappings)
  - deploy_config.sh               — configuration for which Lambdas and env vars to deploy
  - update_lambda.sh               — update lambda code (when changing only code)
  - start_localstack.sh / teardown_localstack.sh — helpers around LocalStack lifecycle
- docker-compose.yml               — LocalStack and test runner services
- docker-test.Dockerfile           — test runner image to run pytest inside Docker (no local test installs needed)
- tests/                           — unit tests (in repo; run in Docker)

Lambda Implementation Details
-----------------------------------
- upload_images.handler
  - Input: user_id, filename, content_type
  - Action: generate presigned PUT URL, create DDB item:
    - status = "PENDING_UPLOAD"
    - created_at timestamp, s3_key
  - Response: upload URL + metadata
  - Logging: debug + warnings for malformed requests

- list_images.handler
  - Input: user_id (required), optional filename (substring), content_type (exact), page_token
  - Action: Query DynamoDB (KeyCondition user_id) + optional FilterExpressions; paginates (max 10)
  - Response: list items; for items with status == "UPLOADED" include bucket, s3_key and presigned GET; otherwise omit S3 fields
  - Logging: request, filters, query param debug

- delete_images.handler
  - Input: user_id, image_id
  - Action: Fetch DDB item; if status == "UPLOADED" delete object from S3; delete item from DDB; return result booleans
  - Logging: per-step debug & exception logs

- s3_listener.handler
  - Trigger: SQS messages (S3 notifications forwarded into SQS)
  - Action: Parse S3 event(s), derive user_id & image_id from key format, update DDB status -> "UPLOADED"
  - Logging: message-by-message processing results

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
