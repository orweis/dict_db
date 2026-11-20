"""Opt-in tests against live servers.

They are skipped unless ``DICT_DB_REDIS_URL`` / ``DICT_DB_ELASTIC_URL`` is
set. Point them at disposable servers: they create and delete keys and an
index whose names start with ``dict-db-it-``. Run with::

    DICT_DB_REDIS_URL=redis://localhost:6379/15 \\
    DICT_DB_ELASTIC_URL=http://localhost:9200 pytest -m integration
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.integration

REDIS_URL = os.environ.get("DICT_DB_REDIS_URL")
ELASTIC_URL = os.environ.get("DICT_DB_ELASTIC_URL")


def _name() -> str:
    return f"dict-db-it-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def live_redis():
    if not REDIS_URL:
        pytest.skip("set DICT_DB_REDIS_URL to run live Redis tests")
    from dict_db.redis_ds.redis_pipe import RedisPipe

    client = RedisPipe.from_url(REDIS_URL)
    prefix = _name()
    yield client, prefix
    for key in client.scan_iter(match=f"*{prefix}*"):
        client.delete(key)


@pytest.fixture
def live_docs():
    if not ELASTIC_URL:
        pytest.skip("set DICT_DB_ELASTIC_URL to run live Elasticsearch tests")
    from elasticsearch import Elasticsearch

    from dict_db.elastic_ds.doc_dict import ElasticDocDict

    es = Elasticsearch(ELASTIC_URL)
    docs = ElasticDocDict(_name(), "it", es=es, refresh="wait_for")
    yield docs
    es.indices.delete(index=docs.index_name, ignore_unavailable=True)


def test_redis_round_trip(live_redis):
    from dict_db.redis_ds.redis_hash_dict import ExpirableJSONRedisHashDict, JSONRedisHashDict
    from dict_db.redis_ds.redis_list import JSONRedisList
    from dict_db.redis_ds.redis_set import JSONRedisSet

    client, prefix = live_redis

    hd = JSONRedisHashDict(f"{prefix}:hash", redis_client=client)
    hd["a"] = {"x": [1, 2]}
    assert hd["a"] == {"x": [1, 2]}
    assert "a" in hd and len(hd) == 1
    del hd["a"]
    assert "a" not in hd

    exp = ExpirableJSONRedisHashDict(f"{prefix}:exp", redis_client=client)
    exp["k"] = 1
    assert exp["k"] == 1

    lst = JSONRedisList(f"{prefix}:list", redis_client=client)
    lst.append("one")
    lst.append({"two": 2})
    assert list(lst) == ["one", {"two": 2}]

    st = JSONRedisSet(f"{prefix}:set", redis_client=client)
    st.add("v")
    assert "v" in st


def test_elastic_round_trip(live_docs):
    docs = live_docs
    docs["str"] = "a"
    docs["num"] = 1
    docs["dict"] = {"a.b": "123", "n": 5}
    docs["str"] = "b"  # overwrite must not duplicate the key
    assert docs["str"] == "b"
    assert docs["num"] == 1
    assert docs["dict"] == {"a.b": "123", "n": 5}
    assert sorted(docs.keys()) == ["dict", "num", "str"]

    docs.upsert("dict", {"extra": True})
    assert docs["dict"]["extra"] is True

    del docs["num"]
    assert "num" not in docs
    assert sorted(docs.keys()) == ["dict", "str"]

    with docs:
        for i in range(5):
            docs[f"bulk{i}"] = i
    assert docs["bulk4"] == 4
    assert len(docs) == 7

    docs.delete_all()
    assert docs.keys() == []
