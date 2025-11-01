"""Process S3->SQS notifications: mark corresponding DDB item as UPLOADED."""

import os
import json
import logging
import urllib.parse
from common.aws_clients import boto3_client, deserialize_item

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

DDB = boto3_client("dynamodb")
S3 = boto3_client("s3")

# Environment
TABLE_NAME = os.environ.get("TABLE_NAME", "ImagesMetadata")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "image-service-root")


def respond(status, body):
    return {"statusCode": status, "body": json.dumps(body)}


def _parse_s3_key(s3_key: str):
    """Expect key format: {user_id}/{image_id}_{filename} -> return (user_id, image_id)"""
    if not s3_key:
        return None, None
    s3_key = urllib.parse.unquote_plus(s3_key)
    parts = s3_key.split("/", 1)
    if len(parts) != 2:
        return None, None
    user_id = parts[0]
    tail = parts[1]
    image_id = tail.split("_", 1)[0] if "_" in tail else None
    return user_id, image_id


def _update_ddb_status(user_id: str, image_id: str):
    logger.debug(f"Updating DDB status to UPLOADED for user_id={user_id}, image_id={image_id}")
    try:
        DDB.update_item(
            TableName=TABLE_NAME,
            Key={"user_id": {"S": str(user_id)}, "image_id": {"S": str(image_id)}},
            UpdateExpression="SET #s = :st",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":st": {"S": "UPLOADED"}},
            ReturnValues="ALL_NEW",
        )
        logger.debug("DynamoDB update_item succeeded")
        return True
    except Exception:
        logger.exception("DynamoDB update_item failed")
        return False


def handler(event, context):
    """
    Lambda triggered by SQS (S3 notifications forwarded to SQS).
    Expects event['Records'] from SQS; each record.body is an S3 event JSON.
    For each S3 record set corresponding DynamoDB item status -> UPLOADED.
    """
    logger.debug(f"Event received: {json.dumps(event)}")
    logger.debug(f"Environment: BUCKET_NAME={BUCKET_NAME}, TABLE_NAME={TABLE_NAME}")

    processed = []
    try:
        records = event.get("Records", []) or []
        logger.debug(f"Number of SQS records: {len(records)}")
        for rec in records:
            try:
                body = rec.get("body")
                logger.debug(f"SQS message body: {body}")
                s3_event = json.loads(body) if isinstance(body, str) else body
                # s3_event contains its own Records array
                for s3rec in s3_event.get("Records", []):
                    s3_info = s3rec.get("s3", {})
                    bucket = s3_info.get("bucket", {}).get("name")
                    key = s3_info.get("object", {}).get("key")
                    logger.debug(f"Received S3 event for bucket={bucket}, key={key}")
                    user_id, image_id = _parse_s3_key(key)
                    logger.debug(f"Parsed user_id={user_id}, image_id={image_id}")
                    if not user_id or not image_id:
                        logger.warning(f"Could not parse user_id/image_id from key={key}; skipping")
                        processed.append({"key": key, "status": "skipped", "reason": "parse_failed"})
                        continue

                    ok = _update_ddb_status(user_id, image_id)
                    processed.append({"user_id": user_id, "image_id": image_id, "s3_key": key, "ddb_updated": ok})
            except Exception as inner:
                logger.exception("Failed processing SQS record")
                processed.append({"error": str(inner)})
        logger.debug(f"Processing result: {json.dumps(processed)}")
        return respond(200, {"processed": processed})
    except Exception as e:
        logger.exception("Unhandled error in process_s3_event handler")
        return respond(500, {"error": str(e)})