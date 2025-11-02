import json
from unittest.mock import MagicMock
import lambdas.list_images.handler as list_mod

def test_list_images_returns_signed_urls_only_for_uploaded(patch_clients, mock_s3, mock_ddb):
    patch_clients(list_mod)

    # Prepare DDB.query to return two items (AttributeValue style) - deserialize_items will be monkeypatched
    mock_ddb.query.return_value = {"Items": [{"dummy": {"S": "1"}}, {"dummy": {"S": "2"}}], "LastEvaluatedKey": {"user_id": {"S": "alice"}, "image_id": {"S": "next"}}}

    # Monkeypatch deserialize_items to return deserialized python dicts
    def fake_deserialize(items):
        return [
            {"image_id": "img1", "filename": "a.png", "content_type": "image/png", "status": "UPLOADED", "s3_key": "alice/img1_a.png"},
            {"image_id": "img2", "filename": "b.png", "content_type": "image/png", "status": "PENDING_UPLOAD", "s3_key": "alice/img2_b.png"},
        ]
    list_mod.deserialize_items = fake_deserialize

    # call handler
    ev = {"body": json.dumps({"user_id": "alice"})}
    resp = list_mod.handler(ev, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["count"] == 2
    items = body["items"]
    # first item should include signed_url and s3 info
    assert items[0]["status"] == "UPLOADED"
    assert "signed_url" in items[0] and items[0]["signed_url"] is not None
    # second should NOT include signed_url or s3_key/bucket in the response per spec
    assert items[1]["status"] == "PENDING_UPLOAD"
    assert "signed_url" not in items[1]
    # pagination token returned
    assert "next_page_token" in body

def test_list_images_missing_userid_returns_400(patch_clients, mock_s3, mock_ddb):
    patch_clients(list_mod)
    ev = {"body": json.dumps({})}
    resp = list_mod.handler(ev, None)
    assert resp["statusCode"] == 400