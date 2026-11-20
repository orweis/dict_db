import pytest

from dict_db.redis_ds.redis_set import JSONRedisSet, PickleRedisSet, RedisSet


@pytest.mark.parametrize("cls", [RedisSet, PickleRedisSet, JSONRedisSet])
def test_set_behaviour(cls, client):
    rs = cls("s", redis_client=client)
    assert len(rs) == 0
    rs.add("a")
    rs.add("a")
    rs.update(("a", "b"))
    assert len(rs) == 2
    assert sorted(rs) == ["a", "b"]
    assert ("a" in rs) is True
    assert ("z" in rs) is False
    assert rs.pop() in ("a", "b")
    assert len(rs) == 1
    assert rs.pop() in ("a", "b")
    assert len(rs) == 0
    assert rs.pop() is None


def test_update_with_empty_iterable_is_noop(client):
    rs = RedisSet("s", redis_client=client)
    rs.update([])
    assert len(rs) == 0


def test_remove_and_delete_all(client):
    rs = JSONRedisSet("s", redis_client=client)
    rs.update([1, 2, 3])
    rs.remove(2)
    rs.remove(42)  # missing values are ignored
    assert sorted(rs) == [1, 3]
    assert repr(rs).startswith("RedisSet(")
    rs.delete_all()
    assert not client.exists("s")
    assert rs.client is client
