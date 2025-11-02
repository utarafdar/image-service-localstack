import json
from unittest.mock import MagicMock
import lambdas.upload_images.handler as upload_mod

def make_event(payload):
    return {"body": json.dumps(payload)}

def test_upload_images_generates_presign_and_writes_ddb(patch_clients, mock_s3, mock_ddb, env_vars):
    # apply patches to module
    patch_clients(upload_mod)

    mock_s3.generate_presigned_url.return_value = "https://signed-put.example/obj"
    # call handler
    ev = make_event({"user_id": "alice", "filename": "pic.png", "content_type": "image/png"})
    resp = upload_mod.handler(ev, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "upload_url" in body or "uploadUrl" in body or body.get("upload_url", body.get("uploadUrl"))
    # DDB.put_item called with expected keys
    assert mock_ddb.put_item.called
    args, kwargs = mock_ddb.put_item.call_args
    assert "TableName" in kwargs or len(args) >= 1

def test_upload_images_missing_userid_returns_400(patch_clients, mock_s3, mock_ddb):
    patch_clients(upload_mod)
    ev = make_event({"filename": "pic.png"})
    resp = upload_mod.handler(ev, None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "error" in body