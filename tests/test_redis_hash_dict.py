import os
import pickle
import time

import pytest

from dict_db.redis_ds.redis_hash_dict import (
    ExpirableJSONRedisHashDict,
    ExpirablePickleRedisHashDict,
    ExpirableRedisHashDict,
    JSONRedisHashDict,
    PickleRedisHashDict,
    RedisHashDict,
)

ALL_HASH_CLASSES = [RedisHashDict, PickleRedisHashDict, JSONRedisHashDict]
ALL_EXPIRABLE = [ExpirableRedisHashDict, ExpirablePickleRedisHashDict, ExpirableJSONRedisHashDict]


@pytest.mark.parametrize("cls", ALL_HASH_CLASSES + ALL_EXPIRABLE)
def test_basic_mapping_behaviour(cls, client):
    d = cls("h", redis_client=client)
    assert len(d) == 0
    assert "k" not in d
    d["k"] = 10
    assert "k" in d
    assert len(d) == 1
    assert d["k"] in ("10", 10)
    assert d.keys() == ["k"]
    del d["k"]
    assert "k" not in d
    assert len(d) == 0


def test_keys_and_items_are_str(client):
    d = JSONRedisHashDict("h", redis_client=client)
    d["a"] = 1
    d[2] = "two"
    assert sorted(d.keys()) == ["2", "a"]
    assert dict(d.iteritems()) == {"a": 1, "2": "two"}
    assert sorted(d) == ["2", "a"]
    assert sorted(d.itervalues(), key=str) == [1, "two"]


def test_missing_key(client):
    d = JSONRedisHashDict("h", redis_client=client)
    with pytest.raises(KeyError):
        d["missing"]
    assert d.get("missing", 5) == 5
    assert d.__delitem__("missing") == 0


def test_get_keeps_falsy_values(client):
    d = JSONRedisHashDict("h", redis_client=client)
    d["zero"] = 0
    assert d.get("zero", "default") == 0


def test_upsert_merges_new_data(client):
    """Regression: 1.x discarded the caller's data."""
    d = JSONRedisHashDict("h", redis_client=client)
    d.upsert("k", {"a": 1})
    assert d["k"] == {"a": 1}
    d.upsert("k", {"b": 2, "a": 3})
    assert d["k"] == {"a": 3, "b": 2}


def test_upsert_replaces_non_dict_value(client):
    d = JSONRedisHashDict("h", redis_client=client)
    d["k"] = "scalar"
    d.upsert("k", {"a": 1})
    assert d["k"] == {"a": 1}


def test_iteritems_cursor_terminates_and_deserializes(client):
    d = JSONRedisHashDict("h", redis_client=client)
    expected = {f"k{i}": {"i": i} for i in range(50)}
    d.update(expected)
    items = list(d.iteritems_cursor())
    assert {k: v for _cursor, (k, v) in items} == expected
    assert items[-1][0] == 0
    assert list(JSONRedisHashDict("empty", redis_client=client).iteritems_cursor()) == []


def test_increment_key(client):
    d = RedisHashDict("h", redis_client=client)
    assert d.increment_key("n") == 1
    assert d.increment_key("n", 2) == 3
    assert d.increment_key("f", 0.5) == pytest.approx(0.5)
    with pytest.raises(TypeError):
        d.increment_key("n", None)


def test_delete_all(client):
    d = JSONRedisHashDict("h", redis_client=client)
    d["a"] = 1
    d.delete_all()
    assert len(d) == 0
    assert not client.exists("h")


def test_client_property_and_default_client(client):
    from dict_db.redis_ds import redis_config

    redis_config.set_client(client)
    assert RedisHashDict("h").client is client


# -- expirable -----------------------------------------------------------


def test_expiration_metadata_is_not_pickled(client):
    """Security regression: 1.x stored (and unpickled) expirations with pickle."""
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    d.set("k", "v", timeout=100)
    raw = client.hget(d.expiration_key, "k")
    assert float(raw) == pytest.approx(time.time() + 100, abs=5)


def test_malicious_pickled_metadata_is_never_executed(client, tmp_path):
    marker = tmp_path / "pwned"

    class Exploit:
        def __reduce__(self):
            return (os.mkdir, (str(marker),))

    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    d["k"] = "v"
    client.hset(d.expiration_key, "k", pickle.dumps(Exploit()))
    assert d["k"] == "v"
    assert d.get_expiration("k") is None
    assert not marker.exists()


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [(b"F1478000000.5\n.", 1478000000.5), (b"I1478000000\n.", 1478000000.0), (b"N.", None)],
)
def test_legacy_python2_pickled_metadata_is_parsed_safely(client, legacy, expected):
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    client.hset(d.expiration_key, "k", legacy)
    assert d.get_expiration("k") == expected


def test_legacy_expired_key_is_expired(client):
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    d["k"] = "v"
    client.hset(d.expiration_key, "k", b"F1.0\n.")
    assert "k" not in d


def test_default_expiration(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    d.set_default_expiration(10)
    assert d.default_expiration == 10
    d["k"] = "v"
    assert d.get_expiration("k") == 1010.0
    assert "k" in d
    now[0] = 1011.0
    assert "k" not in d
    assert d.should_expire("k")
    assert d.always_get("k") == "v"
    with pytest.raises(ExpirableRedisHashDict.KeyExpiredError):
        d["k"]
    # Reading an expired key deletes both the value and its metadata.
    assert not client.hexists("h", "k")
    assert not client.hexists(d.expiration_key, "k")


def test_get_returns_default_for_expired_key(client):
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    d.set("k", "v", timeout=-1)
    assert d.get("k", "gone") == "gone"
    assert not client.hexists("h", "k")


def test_set_with_and_without_timeout(client, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    assert d.get_expiration_as_text("k") == "Never"
    d.set("k", "v", timeout=5)
    assert d.get_expiration("k") == 1005.0
    assert d.get_expiration_as_text("k") == time.ctime(1005.0)
    d.set("k", "v2")
    assert d.get_expiration("k") is None
    d.expire("k", 3)
    assert d.get_expiration("k") == 1003.0
    d.expire("k", None)
    assert d.get_expiration("k") is None


def test_reassigning_a_key_resets_its_expiration(client):
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    d.set("k", "v", timeout=-1)
    d["k"] = "fresh"
    assert d["k"] == "fresh"


def test_delete_removes_metadata(client):
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    d.set("k", "v", timeout=100)
    del d["k"]
    assert not client.hexists(d.expiration_key, "k")
    d.set("a", "v", timeout=100)
    d.delete_all()
    assert not client.exists("h")
    assert not client.exists(d.expiration_key)


def test_iter_fresh_items(client, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    d.set("fresh", 1, timeout=10)
    d.set("forever", 2)
    d.set("stale", 3, timeout=-10)
    assert dict(d.iter_fresh_items()) == {"fresh": 1, "forever": 2}


def test_uses_injected_client(client):
    d = ExpirableJSONRedisHashDict("h", redis_client=client)
    assert d.client is client
