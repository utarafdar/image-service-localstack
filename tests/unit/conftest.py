import os
import json
import pytest
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    # sensible defaults for handlers
    monkeypatch.setenv("BUCKET_NAME", os.environ.get("BUCKET_NAME", "image-service-root"))
    monkeypatch.setenv("TABLE_NAME", os.environ.get("TABLE_NAME", "ImagesMetadata"))
    monkeypatch.setenv("PRESIGN_EXP", os.environ.get("PRESIGN_EXP", "900"))
    monkeypatch.setenv("PAGE_SIZE", os.environ.get("PAGE_SIZE", "10"))
    return monkeypatch

@pytest.fixture
def mock_s3():
    m = MagicMock()
    m.generate_presigned_url = MagicMock(return_value="https://signed.example/object")
    m.delete_object = MagicMock(return_value={})
    return m

@pytest.fixture
def mock_ddb():
    m = MagicMock()
    # default stubs; test cases override return_value as needed
    m.put_item = MagicMock(return_value={})
    m.query = MagicMock(return_value={"Items": [],})
    m.get_item = MagicMock(return_value={})
    m.update_item = MagicMock(return_value={})
    m.delete_item = MagicMock(return_value={})
    return m

@pytest.fixture
def patch_clients(monkeypatch, mock_s3, mock_ddb):
    """
    Replace module-level S3/DDB objects inside each lambda module after import.
    Tests will import handler modules and then rely on these monkeypatches.
    """
    # provide factory to apply replacements after import
    def _apply(module):
        # set attributes used in handlers
        setattr(module, "S3", mock_s3)
        setattr(module, "DDB", mock_ddb)
        return module
    return _apply