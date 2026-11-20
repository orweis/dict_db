import pytest

from dict_db.redis_ds.redis_path_dict import RedisPathDict


@pytest.fixture(params=["pipe", "plain"])
def any_client(request, client, plain_client):
    return client if request.param == "pipe" else plain_client


def test_basic_mapping_behaviour(any_client):
    d = RedisPathDict("users", redis_client=any_client)
    assert len(d) == 0
    assert "k" not in d
    d["k"] = 10
    assert "k" in d
    assert len(d) == 1
    assert d["k"] == "10"
    assert any_client.get("PathDict|users|k") == b"10"
    assert list(d) == ["k"]
    del d["k"]
    assert "k" not in d
    assert len(d) == 0
    assert not any_client.exists("PathDict|users|k")


def test_keys_are_logical_and_filterable(client):
    d = RedisPathDict("p", redis_client=client)
    d["a1"] = 1
    d["a2"] = 2
    d["b"] = 3
    assert sorted(d.keys()) == ["a1", "a2", "b"]
    assert sorted(d.keys("a*")) == ["a1", "a2"]
    assert dict(d.iteritems()) == {"a1": "1", "a2": "2", "b": "3"}
    assert sorted(d.itervalues()) == ["1", "2", "3"]


def test_paths_do_not_leak_between_dicts(client):
    a = RedisPathDict("a", redis_client=client)
    b = RedisPathDict("b", redis_client=client)
    a["k"] = 1
    assert "k" not in b
    assert len(b) == 0


def test_missing_key(client):
    d = RedisPathDict("p", redis_client=client)
    with pytest.raises(KeyError) as excinfo:
        d["missing"]
    assert excinfo.value.args == ("missing",)
    assert d.get("missing", "x") == "x"
    del d["missing"]  # not an error


def test_get(client):
    d = RedisPathDict("p", redis_client=client)
    d["k"] = "v"
    assert d.get("k") == "v"


def test_delete_all_removes_every_item_and_index(client):
    d = RedisPathDict("p", redis_client=client)
    for i in range(5):
        d[f"k{i}"] = i
    other = RedisPathDict("other", redis_client=client)
    other["keep"] = 1
    d.delete_all()
    assert len(d) == 0
    assert client.keys("*PathDict|p|*") == []
    assert other["keep"] == "1"
    d.delete_all()  # empty dict is fine


def test_writes_are_atomic(client):
    d = RedisPathDict("p", redis_client=client)
    with pytest.raises(RuntimeError), client:
        d["k"] = 1
        raise RuntimeError
    assert "k" not in d
    assert len(d) == 0


def test_write_inside_outer_transaction(client):
    d = RedisPathDict("p", redis_client=client)
    with client:
        d["a"] = 1
        d["b"] = 2
    assert sorted(d) == ["a", "b"]


def test_expire_and_default_expiration(client):
    d = RedisPathDict("p", redis_client=client)
    d["k"] = 1
    d.expire("k", 20)
    assert 0 < client.ttl("PathDict|p|k") <= 20
    d.set_default_expiration(30)
    d["j"] = 1
    assert 0 < client.ttl("PathDict|p|j") <= 30


def test_iteration_skips_keys_expired_by_redis(client):
    d = RedisPathDict("p", redis_client=client)
    d["k"] = 1
    d["gone"] = 2
    client.delete("PathDict|p|gone")  # as if its TTL elapsed
    assert dict(d.iteritems()) == {"k": "1"}
