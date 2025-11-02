import json
from unittest.mock import MagicMock
import lambdas.delete_images.handler as delete_mod

def test_delete_images_deletes_s3_only_when_uploaded(patch_clients, mock_s3, mock_ddb):
    patch_clients(delete_mod)
    # prepare _get_ddb_item to return uploaded item
    uploaded_item = {"user_id": "alice", "image_id": "img1", "status": "UPLOADED", "s3_key": "alice/img1_a.png"}
    # monkeypatch module-level helper to return item
    delete_mod.deserialize_item = lambda x: uploaded_item
    delete_mod._get_ddb_item = lambda u, i: uploaded_item

    ev = {"body": json.dumps({"user_id": "alice", "image_id": "img1"})}
    resp = delete_mod.handler(ev, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["s3_deleted"] is True or body["s3_deleted"]  # delete attempted
    assert body["ddb_deleted"] is True or body["ddb_deleted"]
    assert mock_s3.delete_object.called
    assert mock_ddb.delete_item.called

def test_delete_images_skips_s3_when_not_uploaded(patch_clients, mock_s3, mock_ddb):
    patch_clients(delete_mod)
    not_uploaded_item = {"user_id": "alice", "image_id": "img2", "status": "PENDING_UPLOAD", "s3_key": "alice/img2_b.png"}
    delete_mod.deserialize_item = lambda x: not_uploaded_item
    delete_mod._get_ddb_item = lambda u, i: not_uploaded_item

    ev = {"body": json.dumps({"user_id": "alice", "image_id": "img2"})}
    resp = delete_mod.handler(ev, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["s3_deleted"] is False
    assert mock_s3.delete_object.called is False or mock_s3.delete_object.call_count == 0
    assert mock_ddb.delete_item.called