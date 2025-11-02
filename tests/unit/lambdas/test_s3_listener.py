import json
from unittest.mock import MagicMock
import lambdas.s3_listener.handler as sl_mod

def make_s3_event(bucket, key):
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key}
                }
            }
        ]
    }

def test_s3_listener_updates_ddb_for_sqs_records(patch_clients, mock_s3, mock_ddb):
    patch_clients(sl_mod)
    # Build SQS-style event: body is JSON string of S3 event
    s3_event = make_s3_event("image-service-root", "alice/img1_a.png")
    sqs_event = {"Records": [{"body": json.dumps(s3_event)}]}
    resp = sl_mod.handler(sqs_event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    # ensure update_item was called
    assert mock_ddb.update_item.called
    args, kwargs = mock_ddb.update_item.call_args
    assert "TableName" in kwargs or len(args) >= 1