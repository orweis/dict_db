import pytest

import dict_db
from dict_db import Consts, DictDbFactory
from dict_db.elastic_ds.doc_dict import ElasticDocDict
from dict_db.redis_ds.redis_hash_dict import JSONRedisHashDict
from dict_db.redis_ds.redis_list import JSONRedisList


def test_public_api_and_version():
    assert dict_db.__version__ == "2.0.0"
    assert {"Consts", "DictDbFactory"} <= set(dict_db.__all__)


def test_redis_dict(client):
    db = DictDbFactory(Consts.DB_REDIS, client=client).create("test", "sample")
    assert isinstance(db, JSONRedisHashDict)
    assert db.hash_key == "test_sample"
    db["1"] = "Hello Db!"
    assert dict(db.iteritems()) == {"1": "Hello Db!"}
    assert db.client is client


@pytest.mark.parametrize("name", ["", None])
def test_redis_key_without_name(client, name):
    assert DictDbFactory(Consts.DB_REDIS, client=client).create("test", name).hash_key == "test"


def test_redis_list(client):
    factory = DictDbFactory(Consts.DB_REDIS, default_ds_type=Consts.DS_LIST, client=client)
    lst = factory.create("test", "l")
    assert isinstance(lst, JSONRedisList)
    lst.append({"a": 1})
    assert lst[0] == {"a": 1}


def test_elastic_dict(fake_es):
    db = DictDbFactory(Consts.DB_ELASTIC, client=fake_es).create("test", "sample")
    assert isinstance(db, ElasticDocDict)
    db["1"] = "Hello Db!"
    assert dict(db.iteritems()) == {"1": "Hello Db!"}


def test_elastic_list_not_implemented(fake_es):
    with pytest.raises(NotImplementedError):
        DictDbFactory(Consts.DB_ELASTIC, client=fake_es).create("a", "b", Consts.DS_LIST)


def test_unknown_types_raise():
    with pytest.raises(ValueError):
        DictDbFactory("mongo")
    with pytest.raises(ValueError):
        DictDbFactory(Consts.DB_REDIS).create("a", "b", ds_type="tree")
