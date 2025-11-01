"""Lambda function to delete an image: remove object from S3 and item from DynamoDB."""

import os
import json
import logging
from common.aws_clients import boto3_client, deserialize_item

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

S3 = boto3_client("s3")
DDB = boto3_client("dynamodb")

# Environment configuration
BUCKET_NAME = os.environ.get("BUCKET_NAME", "image-service-root")
TABLE_NAME = os.environ.get("TABLE_NAME", "ImagesMetadata")


def respond(status, body):
    return {"statusCode": status, "body": json.dumps(body)}


def _get_ddb_item(user_id: str, image_id: str):
    """Fetch item from DynamoDB (returns deserialized dict or None)."""
    logger.debug(f"Fetching DDB item for user_id={user_id}, image_id={image_id}")
    resp = DDB.get_item(
        TableName=TABLE_NAME,
        Key={"user_id": {"S": str(user_id)}, "image_id": {"S": str(image_id)}},
        ConsistentRead=True,
    )
    item = resp.get("Item")
    if not item:
        logger.debug("DynamoDB item not found")
        return None
    des = deserialize_item(item)
    logger.debug(f"Deserialized DDB item: {json.dumps(des)}")
    return des


def _delete_s3_object(bucket: str, key: str):
    """Delete object from S3, return True on success."""
    logger.debug(f"Deleting S3 object: bucket={bucket}, key={key}")
    try:
        S3.delete_object(Bucket=bucket, Key=key)
        logger.debug("S3 delete_object succeeded")
        return True
    except Exception:
        logger.exception(f"S3 delete_object failed for key={key}")
        return False


def _delete_ddb_item(user_id: str, image_id: str):
    """Delete item from DynamoDB."""
    logger.debug(f"Deleting DDB item for user_id={user_id}, image_id={image_id}")
    try:
        DDB.delete_item(
            TableName=TABLE_NAME,
            Key={"user_id": {"S": str(user_id)}, "image_id": {"S": str(image_id)}},
        )
        logger.debug("DynamoDB delete_item succeeded")
        return True
    except Exception:
        logger.exception("DynamoDB delete_item failed")
        return False


def handler(event, context):
    """
    Expects JSON body:
      { "user_id": "user123", "image_id": "uuid-or-id" }
    Optionally can accept queryStringParameters with same keys.
    """
    logger.debug(f"Event received: {json.dumps(event)}")
    logger.debug(f"Environment: BUCKET_NAME={BUCKET_NAME}, TABLE_NAME={TABLE_NAME}")

    try:
        body = event.get("body")
        payload = json.loads(body) if isinstance(body, str) and body else (body or {})
        if not payload:
            payload = event.get("queryStringParameters") or {}
        logger.debug(f"Parsed payload: {json.dumps(payload)}")

        user_id = payload.get("user_id")
        image_id = payload.get("image_id")

        if not user_id or not image_id:
            logger.warning("Missing required fields user_id or image_id")
            return respond(400, {"error": "user_id and image_id are required"})

        # Fetch the DDB item to learn the s3_key (and filename if needed)
        item = _get_ddb_item(user_id, image_id)
        if not item:
            return respond(404, {"error": "image not found"})

        s3_key = item.get("s3_key") or item.get("key")
        # fallback: if s3_key missing, attempt to construct from available data
        if not s3_key:
            filename = item.get("filename")
            if filename:
                s3_key = f"{user_id}/{image_id}_{filename}"
                logger.debug(f"Constructed s3_key fallback={s3_key}")
            else:
                logger.warning("No s3_key or filename available to delete object")
                s3_key = None

        # Delete S3 object only when the DDB item status == "UPLOADED"
        status = item.get("status")
        logger.debug(f"Item status: {status}")
        s3_deleted = True
        if s3_key:
            if status == "UPLOADED":
                logger.debug("Status is UPLOADED; deleting S3 object")
                s3_deleted = _delete_s3_object(BUCKET_NAME, s3_key)
            else:
                logger.info(f"Skipping S3 delete because item status != 'UPLOADED' (status={status})")
                s3_deleted = False
        else:
            logger.debug("Skipping S3 delete since no key provided")
            
        # Delete DynamoDB item
        ddb_deleted = _delete_ddb_item(user_id, image_id)

        resp_body = {
            "image_id": image_id,
            "user_id": user_id,
            "s3_key": s3_key,
            "s3_deleted": s3_deleted,
            "ddb_deleted": ddb_deleted,
        }
        logger.debug(f"Delete result: {json.dumps(resp_body)}")
        return respond(200, resp_body)

    except Exception as e:
        logger.error(f"Unhandled error in delete handler: {str(e)}", exc_info=True)
        return respond(500, {"error": str(e)})