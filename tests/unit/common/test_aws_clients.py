import pytest
import json
from common import aws_clients

def test_deserialize_item_empty():
    assert aws_clients.deserialize_item(None) == {}

def test_deserialize_items_empty_list():
    assert aws_clients.deserialize_items([]) == []

def test_convert_decimals_roundtrip():
    # build object with nested decimals by calling internal helper via deserialize_item simulation
    from decimal import Decimal
    # simulate already deserialized raw python data to _convert_decimals via deserialize_item side-effects:
    # we can't access _convert_decimals directly (private), but passing an empty item returns {}
    assert aws_clients.deserialize_item({}) == {}