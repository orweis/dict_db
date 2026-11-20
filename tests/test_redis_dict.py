import datetime

import pytest

from dict_db.redis_ds.redis_dict import JSONRedisDict, PickleRedisDict, RedisDict


@pytest.mark.parametrize("cls", [RedisDict, PickleRedisDict, JSONRedisDict])
def test_basic_mapping_behaviour(cls, client):
    d = cls(redis_client=client)
    assert "k" not in d
    d["k"] = 10
    assert "k" in d
    assert d["k"] in ("10", 10)
    assert len(d) == 1
    assert d.keys() == ["k"]
    assert list(d) == ["k"]
    assert d.has_key("k")
    del d["k"]
    assert "k" not in d
    assert len(d) == 0


@pytest.mark.parametrize("cls", [JSONRedisDict, PickleRedisDict])
def test_types_are_preserved(cls, client):
    d = cls(redis_client=client)
    d["k"] = {"a": [1, 2]}
    assert d["k"] == {"a": [1, 2]}


def test_missing_key_raises_key_error(client):
    d = JSONRedisDict(redis_client=client)
    with pytest.raises(KeyError):
        d["missing"]


def test_get_keeps_falsy_values(client):
    d = JSONRedisDict(redis_client=client)
    for key, value in {"zero": 0, "empty": "", "false": False, "list": []}.items():
        d[key] = value
        assert d.get(key, "default") == value
    assert d.get("missing", "default") == "default"
    assert d.get("missing") is None


def test_contains_returns_bool(client):
    d = RedisDict(redis_client=client)
    d["k"] = "v"
    assert ("k" in d) is True
    assert ("x" in d) is False


def test_delete_missing_key_is_not_an_error(client):
    d = RedisDict(redis_client=client)
    assert d.__delitem__("missing") == 0


def test_mutable_mapping_helpers(client):
    d = JSONRedisDict(redis_client=client)
    d.update({"a": 1, "b": 2})
    assert dict(d.items()) == {"a": 1, "b": 2}
    assert sorted(d.values()) == [1, 2]
    assert d.pop("a") == 1
    assert d.setdefault("c", 3) == 3
    assert dict(d.iteritems()) == {"b": 2, "c": 3}
    assert sorted(d.iterkeys()) == ["b", "c"]
    assert sorted(d.itervalues()) == [2, 3]
    assert d == {"b": 2, "c": 3}
    assert eval(repr(d)) == {"b": 2, "c": 3}  # noqa: S307 - repr of plain data


def test_keys_pattern_uses_scan(client):
    d = RedisDict(redis_client=client)
    d["user:1"] = "a"
    d["user:2"] = "b"
    d["other"] = "c"
    assert sorted(d.keys("user:*")) == ["user:1", "user:2"]


def test_default_expiration_sets_ttl(client):
    d = RedisDict(redis_client=client)
    d.set_default_expiration(100)
    assert d.default_expiration == 100
    d["k"] = "v"
    assert d["k"] == "v"  # value is not swapped with the expiration (setex order bug)
    assert 0 < client.ttl("k") <= 100


def test_default_expiration_accepts_timedelta(client):
    d = RedisDict(redis_client=client)
    d.set_default_expiration(datetime.timedelta(seconds=50))
    d["k"] = "v"
    assert 0 < client.ttl("k") <= 50


def test_no_default_expiration_means_no_ttl(client):
    d = RedisDict(redis_client=client)
    d["k"] = "v"
    assert client.ttl("k") == -1


def test_expire(client):
    d = RedisDict(redis_client=client)
    d["k"] = "v"
    d.expire("k", 30)
    assert 0 < client.ttl("k") <= 30


def test_increment_key(client):
    d = RedisDict(redis_client=client)
    assert d.increment_key("n") == 1
    assert d.increment_key("n", 5) == 6
    assert d.increment_key("f", 1.5) == pytest.approx(1.5)
    with pytest.raises(TypeError):
        d.increment_key("n", "1")
    with pytest.raises(TypeError):
        d.increment_key("n", True)


def test_works_with_a_plain_redis_client(plain_client):
    d = JSONRedisDict(redis_client=plain_client)
    d["k"] = [1]
    assert d["k"] == [1]
