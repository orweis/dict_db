"""Factory for creating dictionary-like views over a database."""

from __future__ import annotations

from typing import Any


class Consts:
    """Database, data structure and serializer names accepted by the factory."""

    DB_REDIS = "redis"
    DB_ELASTIC = "elastic"

    DS_DICT = "dict"
    DS_LIST = "list"

    SER_JSON = "json"


class DictDbFactory:
    """Create data structures for a database type.

    Example::

        from dict_db import Consts, DictDbFactory

        db = DictDbFactory(Consts.DB_REDIS).create("test", "sample")
        db["1"] = "Hello Db!"
    """

    def __init__(
        self,
        db_type: str,
        default_ds_type: str = Consts.DS_DICT,
        client: Any = None,
    ) -> None:
        """
        :param db_type: :attr:`Consts.DB_REDIS` or :attr:`Consts.DB_ELASTIC`.
        :param default_ds_type: data structure created when ``create`` is not
            given one (:attr:`Consts.DS_DICT` or :attr:`Consts.DS_LIST`).
        :param client: optional ``redis.Redis`` / ``Elasticsearch`` client.
            Defaults to the backend's default client (see the README).
        :raises ValueError: if ``db_type`` is unknown.
        """
        if db_type not in (Consts.DB_REDIS, Consts.DB_ELASTIC):
            raise ValueError(f"unknown db_type {db_type!r}")
        self._db_type = db_type
        self._default_ds_type = default_ds_type
        self._client = client

    def create(self, path: str, name: str | None, ds_type: str | None = None) -> Any:
        """Create a data structure.

        For Redis, the data is stored under the key ``"<path>_<name>"`` (or
        ``path`` when ``name`` is empty): dicts as a JSON hash
        (:class:`~dict_db.redis_ds.redis_hash_dict.JSONRedisHashDict`), lists as
        a JSON list (:class:`~dict_db.redis_ds.redis_list.JSONRedisList`).

        For Elasticsearch, dicts are
        :class:`~dict_db.elastic_ds.doc_dict.ElasticDocDict` with
        ``index=path`` and ``doc_type=name``.

        :raises ValueError: if ``ds_type`` is unknown.
        :raises NotImplementedError: for Elasticsearch lists.
        """
        if ds_type is None:
            ds_type = self._default_ds_type
        if ds_type not in (Consts.DS_DICT, Consts.DS_LIST):
            raise ValueError(f"unknown ds_type {ds_type!r}")

        if self._db_type == Consts.DB_REDIS:
            key = f"{path}_{name}" if isinstance(name, str) and name else path
            if ds_type == Consts.DS_DICT:
                from .redis_ds.redis_hash_dict import JSONRedisHashDict

                return JSONRedisHashDict(key, redis_client=self._client)
            from .redis_ds.redis_list import JSONRedisList

            return JSONRedisList(key, redis_client=self._client)

        if ds_type == Consts.DS_LIST:
            raise NotImplementedError("ElasticSearch list not available yet...")
        from .elastic_ds.doc_dict import ElasticDocDict

        return ElasticDocDict(path, name, es=self._client)


__all__ = ["Consts", "DictDbFactory"]
