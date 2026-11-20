"""Shared fixtures: in-memory Redis (fakeredis) and a fake Elasticsearch client."""

from __future__ import annotations

import copy
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

import fakeredis
import pytest
import redis
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import NotFoundError

from dict_db.elastic_ds.doc_dict import ElasticDocDict
from dict_db.redis_ds import redis_config
from dict_db.redis_ds.redis_pipe import RedisPipe


@pytest.fixture
def fake_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def client(fake_server: fakeredis.FakeServer) -> RedisPipe:
    """A RedisPipe backed by an in-memory fake server."""
    connection_class = getattr(fakeredis, "FakeRedisConnection", None) or fakeredis.FakeConnection
    pool = redis.ConnectionPool(connection_class=connection_class, server=fake_server)
    return RedisPipe(connection_pool=pool)


@pytest.fixture
def plain_client(fake_server: fakeredis.FakeServer) -> fakeredis.FakeRedis:
    """A plain redis client (not a RedisPipe) sharing the same fake server."""
    return fakeredis.FakeRedis(server=fake_server)


@pytest.fixture(autouse=True)
def _reset_default_redis_client():
    redis_config.set_client(None)
    yield
    redis_config.set_client(None)


def _not_found() -> NotFoundError:
    meta = ApiResponseMeta(404, "1.1", HttpHeaders(), 0.0, NodeConfig("http", "localhost", 9200))
    return NotFoundError("not found", meta=meta, body={"found": False})


class FakeElasticsearch:
    """Just enough of the Elasticsearch client API for ElasticDocDict.

    Implements realtime get, and the bulk actions ElasticDocDict uses,
    including an emulation of its two Painless key-index scripts.
    """

    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.bulk_calls: list[list[dict[str, Any]]] = []
        self.fail_ids: set[str] = set()
        self.indices = SimpleNamespace(delete=self._delete_index)
        self.deleted_indices: list[str] = []

    def _delete_index(self, index: str) -> dict[str, Any]:
        if index not in self.data:
            raise _not_found()
        del self.data[index]
        self.deleted_indices.append(index)
        return {"acknowledged": True}

    def get(self, index: str, id: str) -> dict[str, Any]:
        doc = self.data.get(index, {}).get(id)
        if doc is None:
            raise _not_found()
        return {"_index": index, "_id": id, "found": True, "_source": copy.deepcopy(doc)}

    def _run_script(self, doc: dict[str, Any], script: dict[str, Any]) -> None:
        field = script["params"]["field"]
        key = script["params"]["key"]
        if script["source"] == ElasticDocDict.ADD_KEY_SCRIPT:
            doc.setdefault(field, [])
            if key not in doc[field]:
                doc[field].append(key)
        elif script["source"] == ElasticDocDict.REMOVE_KEY_SCRIPT:
            if doc.get(field) is not None:
                doc[field] = [k for k in doc[field] if k != key]
        else:  # pragma: no cover - would be a test bug
            raise AssertionError("unknown script")

    def bulk(self, operations: list[dict[str, Any]], refresh: Any = None) -> dict[str, Any]:
        self.bulk_calls.append(copy.deepcopy(operations))
        items: list[dict[str, Any]] = []
        i = 0
        while i < len(operations):
            ((action, meta),) = operations[i].items()
            index, doc_id = meta["_index"], meta["_id"]
            docs = self.data[index]
            if doc_id in self.fail_ids:
                error = {"type": "mapper_parsing_exception"}
                items.append({action: {"status": 400, "error": error}})
                i += 1 if action == "delete" else 2
                continue
            if action == "index":
                docs[doc_id] = copy.deepcopy(operations[i + 1])
                items.append({"index": {"status": 201, "result": "created"}})
                i += 2
            elif action == "delete":
                found = docs.pop(doc_id, None) is not None
                result = "deleted" if found else "not_found"
                items.append({"delete": {"status": 200 if found else 404, "result": result}})
                i += 1
            elif action == "update":
                body = operations[i + 1]
                i += 2
                if "doc" in body:
                    if doc_id in docs:
                        docs[doc_id].update(copy.deepcopy(body["doc"]))
                    elif body.get("doc_as_upsert"):
                        docs[doc_id] = copy.deepcopy(body["doc"])
                    else:  # pragma: no cover
                        items.append({"update": {"status": 404, "error": {"type": "missing"}}})
                        continue
                elif doc_id in docs:
                    self._run_script(docs[doc_id], body["script"])
                else:
                    docs[doc_id] = copy.deepcopy(body["upsert"])
                items.append({"update": {"status": 200, "result": "updated"}})
            else:  # pragma: no cover
                raise AssertionError(f"unexpected action {action}")
        errors = any("error" in result for item in items for result in item.values())
        return {"errors": errors, "items": items}


@pytest.fixture
def fake_es() -> FakeElasticsearch:
    return FakeElasticsearch()
