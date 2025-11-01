# src/common/aws_clients.py
import os
import boto3
from botocore.config import Config
from boto3.dynamodb.types import TypeDeserializer
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

_deserializer = TypeDeserializer()

def boto3_client(service_name):
    """Create a boto3 client configured for LocalStack"""
    endpoint_url = os.environ.get('LOCALSTACK_ENDPOINT')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    logger.debug(f"boto3_client() called for service: {service_name}")
    logger.debug(f"LOCALSTACK_ENDPOINT={endpoint_url!r}, AWS_REGION={region!r}")
    logger.debug(f"AWS_ACCESS_KEY_ID present: {'AWS_ACCESS_KEY_ID' in os.environ}, AWS_SECRET_ACCESS_KEY present: {'AWS_SECRET_ACCESS_KEY' in os.environ}")

    
    config = Config(
        retries={'max_attempts': 2},
        connect_timeout=5,
        read_timeout=5
    )
    
    try:
        logger.debug("Attempting to create boto3 client...")
        client = boto3.client(
            service_name,
            endpoint_url=endpoint_url or None,
            region_name=region,
            aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID', 'test'),
            aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY', 'test'),
            config=config
        )
        logger.debug(f"boto3 client created successfully for service: {service_name}")
        return client
    except Exception:
        logger.exception(f"Failed to create boto3 client for service: {service_name}")
        raise

def _convert_decimals(obj):
    """Recursively convert Decimal to int or float inside data structures."""
    if isinstance(obj, Decimal):
        # prefer int when there's no fractional part
        if obj == obj.to_integral_value():
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_decimals(v) for v in obj]
    return obj

def deserialize_item(item):
    """
    Convert a single DynamoDB AttributeValue map to a plain Python dict
    with Decimal converted to int/float for JSON serialization.
    """
    if not item:
        return {}
    try:
        raw = {k: _deserializer.deserialize(v) for k, v in item.items()}
        return _convert_decimals(raw)
    except Exception:
        logger.exception("Failed to deserialize DynamoDB item")
        raise

def deserialize_items(items):
    """Deserialize a list of DynamoDB items."""
    return [deserialize_item(it) for it in (items or [])]