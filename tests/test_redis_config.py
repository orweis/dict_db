from dict_db.redis_ds import redis_config
from dict_db.redis_ds.redis_hash_dict import RedisHashDict
from dict_db.redis_ds.redis_pipe import RedisPipe


def test_default_client_is_lazy_and_cached(monkeypatch):
    monkeypatch.delenv(redis_config.ENV_VAR, raising=False)
    first = redis_config.get_client()
    assert isinstance(first, RedisPipe)
    assert redis_config.get_client() is first
    assert redis_config.CLIENT is first
    kwargs = first.connection_pool.connection_kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["db"]) == ("localhost", 6379, 0)


def test_default_client_uses_environment_url(monkeypatch):
    monkeypatch.setenv(redis_config.ENV_VAR, "redis://cache.invalid:7000/5")
    kwargs = redis_config.get_client().connection_pool.connection_kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["db"]) == ("cache.invalid", 7000, 5)


def test_set_client_is_used_by_data_structures(client):
    redis_config.set_client(client)
    d = RedisHashDict("h")
    assert d.client is client


def test_legacy_monkey_patching_of_client_still_works(client):
    redis_config.CLIENT = client
    assert RedisHashDict("h").client is client


def test_unknown_attribute_raises():
    import pytest

    with pytest.raises(AttributeError):
        redis_config.NOT_A_THING  # noqa: B018
