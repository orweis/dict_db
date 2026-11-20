import pytest
from elasticsearch import Elasticsearch
from elasticsearch.helpers import BulkIndexError

from dict_db.elastic_ds import doc_dict as doc_dict_module
from dict_db.elastic_ds.doc_dict import ElasticDocDict, KeyShouldBeStringException


@pytest.fixture
def d(fake_es):
    return ElasticDocDict("Test", "TestDocDict", es=fake_es)


def test_constructor_does_not_touch_the_network(fake_es):
    ElasticDocDict("idx", "t", es=fake_es)
    assert fake_es.bulk_calls == []


def test_index_name(fake_es):
    assert ElasticDocDict("Test", "TestDocDict", es=fake_es).index_name == "test-testdocdict"
    assert ElasticDocDict("Test", None, es=fake_es).index_name == "test"
    assert ElasticDocDict("Test", es=fake_es).client is fake_es


def test_set_get(d):
    d["1"] = "a"
    d["a"] = 1
    d["True"] = True
    d["Dict"] = {"a.b": "123", "5": "ddd", "ddd": 5}
    assert d["1"] == "a"
    assert d["a"] == 1
    assert d["True"] is True
    assert d["Dict"] == {"a.b": "123", "5": "ddd", "ddd": 5}
    assert sorted(d.keys()) == sorted(["1", "a", "True", "Dict"])
    assert len(d) == 4


def test_storage_layout(d, fake_es):
    d["k"] = {"a.b": 1}
    d["v"] = 3
    docs = fake_es.data["test-testdocdict"]
    assert docs["k"] == {"a_;_b": 1}
    assert docs["v"] == {"__value__": 3, "__type__": "int"}
    assert docs[ElasticDocDict.KEYS_ID] == {ElasticDocDict.KEYS_FIELD: ["k", "v"]}


def test_overwriting_does_not_duplicate_keys(d):
    d["k"] = 1
    d["k"] = 2
    assert d.keys() == ["k"]
    assert d["k"] == 2


def test_missing_keys(d):
    with pytest.raises(KeyError):
        d["missing"]
    assert d.get("missing", "x") == "x"
    assert "missing" not in d
    assert not d.has_key("missing")
    with pytest.raises(KeyError):
        del d["missing"]
    with pytest.raises(KeyError):
        d[5]
    assert 5 not in d


@pytest.mark.parametrize("key", [1, None, b"bytes", ("t",)])
def test_keys_must_be_strings(d, key):
    with pytest.raises(KeyShouldBeStringException):
        d[key] = "value"


def test_reserved_key_is_rejected(d):
    with pytest.raises(KeyShouldBeStringException):
        d[ElasticDocDict.KEYS_ID] = {"x": 1}
    d["a"] = 1
    with pytest.raises(KeyError):
        d[ElasticDocDict.KEYS_ID]
    assert ElasticDocDict.KEYS_ID not in d
    with pytest.raises(KeyError):
        del d[ElasticDocDict.KEYS_ID]
    assert d.keys() == ["a"]


def test_iteration(d):
    d["1"] = 1
    d["2"] = 2
    d["3"] = 3
    assert dict(d.iteritems()) == {"1": 1, "2": 2, "3": 3}
    assert list(d.iterkeys()) == ["1", "2", "3"]
    assert sorted(d.values()) == [1, 2, 3]
    assert repr(d) == "{'1': 1, '2': 2, '3': 3}"


def test_set_remove_and_len(d):
    keys = ["1", "2", "3", "4", "5"]
    for count, key in enumerate(keys, start=1):
        d[key] = key
        assert len(d) == count
    for count, key in reversed(list(enumerate(keys))):
        del d[key]
        assert len(d) == count
    assert d.keys() == []


def test_upsert(d, fake_es):
    d.upsert("k", {"a": 1})
    d.upsert("k", {"b.c": 2})
    assert d["k"] == {"a": 1, "b.c": 2}
    assert d.keys() == ["k"]


def test_delete_all(d, fake_es):
    d["a"] = 1
    d["b"] = 2
    d.delete_all()
    assert len(d) == 0
    assert set(fake_es.data["test-testdocdict"]) == {ElasticDocDict.KEYS_ID}
    d.delete_all()


def test_delete_elastic_index(d, fake_es):
    d["a"] = 1
    d.delete_elastic_index()
    assert fake_es.deleted_indices == ["test-testdocdict"]


def test_bulk_mode_buffers_writes(d, fake_es):
    with d:
        d["a"] = 1
        with d:  # re-entrant
            d["b"] = 2
        assert fake_es.bulk_calls == []
    assert len(fake_es.bulk_calls) == 1
    assert dict(d.iteritems()) == {"a": 1, "b": 2}


def test_bulk_mode_flushes_large_batches(d, fake_es):
    with d:
        for i in range(ElasticDocDict.BULK_FLUSH_SIZE // 2 + 1):
            d[str(i)] = i
        assert len(fake_es.bulk_calls) == 1
    assert len(d) == ElasticDocDict.BULK_FLUSH_SIZE // 2 + 1


def test_bulk_errors_are_raised(d, fake_es):
    fake_es.fail_ids.add("bad")
    with pytest.raises(BulkIndexError) as excinfo:
        d["bad"] = 1
    assert len(excinfo.value.errors) == 1


def test_default_client_from_environment(monkeypatch):
    monkeypatch.setenv(doc_dict_module.ENV_VAR, "http://search.invalid:9201")
    d = ElasticDocDict("idx")
    assert isinstance(d.client, Elasticsearch)
    node = d.client.transport.node_pool.all()[0]
    assert (node.config.host, node.config.port) == ("search.invalid", 9201)
