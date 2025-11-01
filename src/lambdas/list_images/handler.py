# src/lambdas/list_images/handler.py
"""Lambda function for listing images for a user with optional filters and pagination."""

import os
import json
import time
import base64
import logging
from common.aws_clients import boto3_client, deserialize_items

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

S3 = boto3_client("s3")
DDB = boto3_client("dynamodb")

# Environment configuration
BUCKET_NAME = os.environ.get("BUCKET_NAME", "image-service-root")
TABLE_NAME = os.environ.get("TABLE_NAME", "ImagesMetadata")
PRESIGN_EXP = int(os.environ.get("PRESIGN_EXP", "900"))  # seconds
PAGE_SIZE = int(os.environ.get("PAGE_SIZE", os.environ.get("PAGE_LIMIT", "10")))


def respond(status, body):
    return {"statusCode": status, "body": json.dumps(body)}


def _encode_token(token_obj):
    return base64.urlsafe_b64encode(json.dumps(token_obj).encode()).decode()


def _decode_token(token_str):
    try:
        return json.loads(base64.urlsafe_b64decode(token_str.encode()).decode())
    except Exception:
        return None


def handler(event, context):
    """
    Expects JSON body (or query params via API gateway mapping) with:
      {
        "user_id": "user123",           # required
        "filename": "pic.png",         # optional (substring match)
        "content_type": "image/png",   # optional (exact match)
        "page_token": "..."            # optional (opaque token returned by previous response)
      }

    Returns paginated list of images (max PAGE_SIZE) with presigned GET URLs.
    """
    logger.debug(f"Event received: {json.dumps(event)}")
    logger.debug(f"Environment: BUCKET_NAME={BUCKET_NAME}, TABLE_NAME={TABLE_NAME}, PAGE_SIZE={PAGE_SIZE}")

    try:
        body = event.get("body")
        # If body is a JSON string (API Gateway proxy), parse it; otherwise allow direct dict
        payload = json.loads(body) if isinstance(body, str) and body else (body or {})
        logger.debug(f"Parsed payload: {json.dumps(payload)}")

        # Allow queryStringParameters fallback (if API Gateway uses GET)
        if not payload:
            qsp = event.get("queryStringParameters") or {}
            payload.update(qsp)
            logger.debug(f"Using queryStringParameters payload: {json.dumps(payload)}")

        user_id = payload.get("user_id")
        if not user_id:
            logger.warning("Missing required field: user_id")
            return respond(400, {"error": "user_id is required"})

        filename_filter = payload.get("filename")
        content_type_filter = payload.get("content_type")
        page_token = payload.get("page_token")

        logger.debug(f"Filters: filename={filename_filter}, content_type={content_type_filter}, page_token={page_token}")

        # Build DynamoDB Query
        key_condition = "user_id = :uid"
        expr_attr_vals = {":uid": {"S": str(user_id)}}
        expr_attr_names = {}

        filter_expr_parts = []
        if filename_filter:
            # contains on filename attribute
            expr_attr_names["#fn"] = "filename"
            expr_attr_vals[":fname"] = {"S": str(filename_filter)}
            filter_expr_parts.append("contains(#fn, :fname)")

        if content_type_filter:
            expr_attr_names["#ct"] = "content_type"
            expr_attr_vals[":ctype"] = {"S": str(content_type_filter)}
            filter_expr_parts.append("#ct = :ctype")

        params = {
            "TableName": TABLE_NAME,
            "KeyConditionExpression": key_condition,
            "ExpressionAttributeValues": expr_attr_vals,
            "Limit": PAGE_SIZE,
        }
        if expr_attr_names:
            params["ExpressionAttributeNames"] = expr_attr_names
        if filter_expr_parts:
            params["FilterExpression"] = " AND ".join(filter_expr_parts)

        # Handle pagination token
        if page_token:
            eks = _decode_token(page_token)
            if eks:
                logger.debug(f"Decoded ExclusiveStartKey: {json.dumps(eks)}")
                params["ExclusiveStartKey"] = eks
            else:
                logger.warning("Failed to decode page_token; ignoring it")

        logger.debug(f"Query params for DynamoDB: {json.dumps({k: v for k, v in params.items() if k != 'ExpressionAttributeValues'})}")
        logger.debug(f"ExpressionAttributeValues present: {list(expr_attr_vals.keys())}")

        # Execute Query
        logger.debug("Executing DynamoDB query...")
        resp = DDB.query(**params)
        items = resp.get("Items", [])
        last_evaluated = resp.get("LastEvaluatedKey")
        logger.debug(f"DynamoDB returned {len(items)} items, LastEvaluatedKey present: {bool(last_evaluated)}")

        # Deserialize items and generate presigned URLs
        results = []
        deserialized = deserialize_items(items)
        for obj in deserialized:
            logger.debug(f"Item deserialized: {json.dumps(obj)}")
            status = obj.get("status")
            s3_key = obj.get("s3_key") or obj.get("key")

            # Base metadata always returned
            item_out = {
                "image_id": obj.get("image_id"),
                "filename": obj.get("filename"),
                "content_type": obj.get("content_type"),
                "created_at": obj.get("created_at"),
                "status": status,
            }

            # Only include S3 info and signed URL when status == "UPLOADED"
            if status == "UPLOADED" and s3_key:
                try:
                    presigned_url = S3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": BUCKET_NAME, "Key": s3_key},
                        ExpiresIn=PRESIGN_EXP,
                        HttpMethod="GET",
                    )
                except Exception as s3_err:
                    logger.error(f"Failed to generate presigned GET for key={s3_key}: {str(s3_err)}")
                    presigned_url = None

                item_out.update({
                    "bucket": obj.get("bucket", BUCKET_NAME),
                    "s3_key": s3_key,
                    "signed_url": presigned_url,
                })
            else:
                logger.debug(f"Skipping S3 signed URL for item image_id={obj.get('image_id')} status={status}")

            results.append(item_out)


        response_payload = {
            "items": results,
            "count": len(results),
            "expires_in": PRESIGN_EXP
        }
        if last_evaluated:
            response_payload["next_page_token"] = _encode_token(last_evaluated)
            logger.debug("Next page token generated")

        logger.debug(f"Returning response with {len(results)} items")
        return respond(200, response_payload)

    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}", exc_info=True)
        return respond(500, {"error": str(e)})