import pickle

import pytest

from dict_db.serialization import (
    JSONSerializer,
    PassThroughSerializer,
    PickleSerializer,
    decode_text,
)


def test_decode_text_decodes_utf8_bytes():
    assert decode_text(b"h\xc3\xa9") == "hé"
    assert decode_text(bytearray(b"x")) == "x"


def test_decode_text_keeps_binary_and_non_bytes():
    assert decode_text(b"\xff\xfe") == b"\xff\xfe"
    assert decode_text(5) == 5
    assert decode_text(None) is None


def test_pass_through_round_trip():
    s = PassThroughSerializer()
    assert s.serialize(10) == 10
    assert s.deserialize(b"10") == "10"


@pytest.mark.parametrize("value", [None, 0, 1.5, "text", [1, "a"], {"a": {"b": [1]}}, True])
def test_json_round_trip(value):
    s = JSONSerializer()
    assert s.deserialize(s.serialize(value).encode()) == value


def test_json_lenient_serialization_is_kept_for_compatibility():
    s = JSONSerializer()
    assert s.serialize(object()) == "null"
    assert s.serialize({("tuple",): 1, "k": 2}) == '{"k": 2}'


def test_json_invalid_data_returns_load_failure():
    s = JSONSerializer()
    result = s.deserialize(b"{not json")
    assert isinstance(result, JSONSerializer.LoadFailure)
    assert result.value == b"{not json"
    assert isinstance(result.err, ValueError)
    assert "LoadFailure" in repr(result)


def test_json_none_is_none():
    assert JSONSerializer().deserialize(None) is None


def test_pickle_round_trip():
    s = PickleSerializer()
    data = s.serialize({"a": (1, 2)})
    assert isinstance(data, bytes)
    assert s.deserialize(data) == {"a": (1, 2)}
    assert s.deserialize(None) is None
    assert pickle.loads(data) == {"a": (1, 2)}


def test_backend_serialization_modules_are_aliases():
    from dict_db.elastic_ds import serialization as es_ser
    from dict_db.redis_ds import serialization as redis_ser

    assert redis_ser.JSONSerializer is JSONSerializer
    assert es_ser.PickleSerializer is PickleSerializer
