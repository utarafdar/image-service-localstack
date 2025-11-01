# src/lambdas/upload_images/handler.py
"""Lambda function for generating S3 presigned upload URLs."""

import os
import json
import time
import uuid
import logging
from common.aws_clients import boto3_client

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

S3 = boto3_client("s3")
DDB = boto3_client("dynamodb")

# Environment configuration
BUCKET_NAME = os.environ.get("BUCKET_NAME", "image-service-root")
TABLE_NAME = os.environ.get("TABLE_NAME", "ImagesMetadata")
PRESIGN_EXP = int(os.environ.get("PRESIGN_EXP", "900"))  # seconds


def respond(status, body):
    return {"statusCode": status, "body": json.dumps(body)}


def handler(event, context):
    """
     Expects JSON body: 
      {
        "user_id": "user123",
        "filename": "pic.png",
        "content_type": "image/png"
      }

    Returns: 
      {
        upload_url, bucket, key, expires_in, image_id
      }

    Also writes metadata to DynamoDB with PK=user_id, SK=image_id
    and status=PENDING_UPLOAD
    """
    logger.debug(f"Event received: {json.dumps(event)}")
    logger.debug(f"Environment: BUCKET_NAME={BUCKET_NAME}, TABLE_NAME={TABLE_NAME}")

    try:
        body = event.get("body")
        logger.debug(f"Raw body: {body}")

        payload = json.loads(body) if isinstance(body, str) else (body or {})
        logger.debug(f"Parsed payload: {json.dumps(payload)}")

        user_id = payload.get("user_id")
        filename = payload.get("filename")
        content_type = payload.get("content_type", "application/octet-stream")
        logger.debug(f"Extracted values: user_id={user_id}, filename={filename}, content_type={content_type}")


        if not user_id or not filename:
            logger.warning("Missing required fields")
            return respond(400, {"error": "user_id and filename are required"})
        
        # Generate IDs and keys
        image_id = str(uuid.uuid4())
        obj_key = f"{user_id}/{image_id}_{filename}"
        logger.debug(f"Generated image_id={image_id}, obj_key={obj_key}")


        # Generate presigned PUT URL
        logger.debug("Generating presigned URL...")
        try:
            upload_url = S3.generate_presigned_url(
                "put_object",
                Params={"Bucket": BUCKET_NAME, "Key": obj_key, "ContentType": content_type},
                ExpiresIn=PRESIGN_EXP,
                HttpMethod="PUT",
            )
            logger.debug("Presigned URL generated successfully")
        except Exception as s3_error:
            logger.error(f"S3 presign error: {str(s3_error)}")
            raise


        # create an item in dynamodb recording pending upload
        now = int(time.time())
        logger.debug("Writing to DynamoDB...")
        try:
            DDB.put_item(
                TableName=TABLE_NAME,
                Item={
                    "user_id": {"S": user_id},
                    "image_id": {"S": image_id},
                    "filename": {"S": filename},
                    "s3_key": {"S": obj_key},
                    "bucket": {"S": BUCKET_NAME},
                    "content_type": {"S": content_type},
                    "status": {"S": "PENDING_UPLOAD"},
                    "created_at": {"N": str(now)},
                },
            )
            logger.debug("DynamoDB write successful")
        except Exception as ddb_error:
            logger.error(f"DynamoDB error: {str(ddb_error)}")
            raise

        response = {
            "upload_url": upload_url,
            "bucket": BUCKET_NAME,
            "key": obj_key,
            "expires_in": PRESIGN_EXP,
            "image_id": image_id,
        }
        logger.debug(f"Returning successful response: {json.dumps(response)}")
        return respond(200, response)

    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}", exc_info=True)
        return respond(500, {"error": str(e)})
