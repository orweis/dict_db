"""A dictionary interface to Elasticsearch documents (elasticsearch-py 8.x/9.x)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from types import TracebackType
from typing import Any

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import BulkIndexError

from .._compat import DictMixin

ENV_VAR = "DICT_DB_ELASTIC_URL"
DEFAULT_URL = "http://localhost:9200"


class Nil:
    """Sentinel type for "no value"."""


NIL = Nil()


class KeyShouldBeStringException(ValueError):
    """Raised when a key is not a ``str`` (or is reserved)."""


def _body(response: Any) -> Any:
    """Return the body of an ``ApiResponse`` (or a plain dict unchanged)."""
    return getattr(response, "body", response)


def default_client() -> Elasticsearch:
    """Create a client from ``DICT_DB_ELASTIC_URL`` (default ``http://localhost:9200``)."""
    return Elasticsearch(os.environ.get(ENV_VAR, DEFAULT_URL))


class ElasticDocDict(DictMixin):
    """A dictionary stored as Elasticsearch documents.

    Every item is stored as one document whose ``_id`` is the item's key, in
    the index ``<index>-<doc_type>`` (lowercased), or ``<index>`` when no
    ``doc_type`` is given. Keys must be strings. The list of keys is kept in
    a bookkeeping document with the reserved id :attr:`KEYS_ID`, updated
    atomically with Painless scripts.

    Dictionary values are stored as the document itself (top-level ``.`` in
    field names is escaped); other values are stored as
    ``{"__value__": value, "__type__": "<type name>"}``.

    Use the dictionary as a context manager to buffer writes into ``_bulk``
    requests::

        with docs:
            for key, value in many_items:
                docs[key] = value
    """

    KEYS_ID = "__ElasticDocDict_Keys"
    KEYS_FIELD = "__ElasticDocDict_keys__"
    DOT_ESCAPE_SEQ = "_;_"
    DOT_CHAR = "."
    VALUE_FIELD_NAME = "__value__"
    TYPE_FIELD_NAME = "__type__"
    BULK_FLUSH_SIZE = 100

    ADD_KEY_SCRIPT = (
        "if (ctx._source[params.field] == null) { ctx._source[params.field] = new ArrayList(); }"
        " if (ctx._source[params.field].contains(params.key)) { ctx.op = 'noop'; }"
        " else { ctx._source[params.field].add(params.key); }"
    )
    REMOVE_KEY_SCRIPT = (
        "if (ctx._source[params.field] == null) { ctx.op = 'noop'; }"
        " else { ctx._source[params.field].removeIf(k -> k == params.key); }"
    )

    def __init__(
        self,
        index: str,
        doc_type: str | None = None,
        es: Elasticsearch | None = None,
        refresh: bool | str = False,
    ) -> None:
        """
        :param index: index name (prefix).
        :param doc_type: optional name appended to the index, which replaces
            the mapping types removed in Elasticsearch 7+.
        :param es: client to use; defaults to :func:`default_client`.
        :param refresh: ``refresh`` argument passed to write requests
            (``True``, ``False`` or ``"wait_for"``). Reads by key are realtime
            regardless; this only matters for searches.
        """
        self._es = es if es is not None else default_client()
        self._index = f"{index}-{doc_type}".lower() if doc_type else index.lower()
        self._doc_type = doc_type
        self._refresh = refresh
        self._bulk_depth = 0
        self._bulk_commands: list[dict[str, Any]] = []

    @property
    def index_name(self) -> str:
        """The Elasticsearch index holding this dictionary."""
        return self._index

    @property
    def client(self) -> Elasticsearch:
        """The underlying Elasticsearch client."""
        return self._es

    # -- serialization ---------------------------------------------------

    def serialize(self, value: Any) -> dict[str, Any]:
        """Convert a value into a document body."""
        if isinstance(value, dict):
            return {self._escape_field(k): v for k, v in value.items()}
        return {self.VALUE_FIELD_NAME: value, self.TYPE_FIELD_NAME: type(value).__name__}

    def deserialize(self, data: dict[str, Any]) -> Any:
        """Convert a document body back into a value."""
        value = data.get(self.VALUE_FIELD_NAME, NIL)
        type_name = data.get(self.TYPE_FIELD_NAME, NIL)
        if isinstance(value, Nil) and isinstance(type_name, Nil):
            return {self._unescape_field(k): v for k, v in data.items()}
        return value

    @classmethod
    def _escape_field(cls, field_name: Any) -> Any:
        """Escape ``.`` in a field name so it is not treated as an object path."""
        if isinstance(field_name, str):
            return field_name.replace(cls.DOT_CHAR, cls.DOT_ESCAPE_SEQ)
        return field_name

    @classmethod
    def _unescape_field(cls, field_name: Any) -> Any:
        """Reverse :meth:`_escape_field`."""
        if isinstance(field_name, str):
            return field_name.replace(cls.DOT_ESCAPE_SEQ, cls.DOT_CHAR)
        return field_name

    # -- low level helpers -------------------------------------------------

    def _validate_key(self, key: Any) -> str:
        if not isinstance(key, str):
            raise KeyShouldBeStringException(
                f"keys must be str (got {type(key).__name__}); they are stored as document ids"
            )
        if key == self.KEYS_ID:
            raise KeyShouldBeStringException(f"{self.KEYS_ID!r} is a reserved key")
        return key

    def _get_source(self, doc_id: str) -> dict[str, Any] | None:
        try:
            response = self._es.get(index=self._index, id=doc_id)
        except NotFoundError:
            return None
        source = _body(response).get("_source")
        return dict(source) if source is not None else {}

    def _key_ops(self, key: str, script: str) -> list[dict[str, Any]]:
        return [
            {"update": {"_index": self._index, "_id": self.KEYS_ID, "retry_on_conflict": 5}},
            {
                "script": {
                    "source": script,
                    "lang": "painless",
                    "params": {"field": self.KEYS_FIELD, "key": key},
                },
                "upsert": {self.KEYS_FIELD: [key] if script == self.ADD_KEY_SCRIPT else []},
            },
        ]

    def _send(self, operations: list[dict[str, Any]]) -> None:
        if not operations:
            return
        response = _body(self._es.bulk(operations=operations, refresh=self._refresh))
        if response.get("errors"):
            errors = [
                item
                for item in response.get("items", [])
                for result in item.values()
                if "error" in result
            ]
            if errors:
                raise BulkIndexError(f"{len(errors)} document(s) failed", errors)

    def _write(self, operations: list[dict[str, Any]]) -> None:
        if self._bulk_depth:
            self._bulk_commands.extend(operations)
            if len(self._bulk_commands) >= 2 * self.BULK_FLUSH_SIZE:
                self.flush()
        else:
            self._send(operations)

    def flush(self) -> None:
        """Send buffered bulk writes now."""
        commands, self._bulk_commands = self._bulk_commands, []
        self._send(commands)

    # -- mapping API ------------------------------------------------------

    def __repr__(self) -> str:
        return repr(dict(self.iteritems()))

    def has_key(self, key: Any) -> bool:
        """Return ``True`` if a document exists for ``key``."""
        return key in self

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str) or key == self.KEYS_ID:
            return False
        return self._get_source(key) is not None

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value of ``key`` or ``default``."""
        try:
            return self[key]
        except KeyError:
            return default

    def __getitem__(self, key: Any) -> Any:
        if not isinstance(key, str) or key == self.KEYS_ID:
            raise KeyError(key)
        source = self._get_source(key)
        if source is None:
            raise KeyError(key)
        return self.deserialize(source)

    def __enter__(self) -> ElasticDocDict:
        self._bulk_depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._bulk_depth -= 1
        if self._bulk_depth == 0:
            # Buffered writes are sent even if the block raised (1.x behaviour).
            self.flush()

    def __setitem__(self, key: Any, value: Any) -> None:
        key = self._validate_key(key)
        operations: list[dict[str, Any]] = [
            {"index": {"_index": self._index, "_id": key}},
            self.serialize(value),
            *self._key_ops(key, self.ADD_KEY_SCRIPT),
        ]
        self._write(operations)

    def upsert(self, key: Any, data: Any) -> None:
        """Merge ``data`` into the document stored at ``key`` (create it if needed)."""
        key = self._validate_key(key)
        operations: list[dict[str, Any]] = [
            {"update": {"_index": self._index, "_id": key, "retry_on_conflict": 5}},
            {"doc": self.serialize(data), "doc_as_upsert": True},
            *self._key_ops(key, self.ADD_KEY_SCRIPT),
        ]
        self._write(operations)

    def keys(self) -> list[str]:  # type: ignore[override]
        """Return the list of keys."""
        source = self._get_source(self.KEYS_ID) or {}
        return list(source.get(self.KEYS_FIELD) or [])

    def __len__(self) -> int:
        return len(self.keys())

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __delitem__(self, key: Any) -> None:
        if not isinstance(key, str) or key == self.KEYS_ID:
            raise KeyError(key)
        if key not in self and key not in self.keys():
            raise KeyError(key)
        self._send(
            [
                {"delete": {"_index": self._index, "_id": key}},
                *self._key_ops(key, self.REMOVE_KEY_SCRIPT),
            ]
        )

    def delete_all(self) -> None:
        """Remove all keys and their documents."""
        operations: list[dict[str, Any]] = [
            {"delete": {"_index": self._index, "_id": key}} for key in self.keys()
        ]
        operations += [
            {"index": {"_index": self._index, "_id": self.KEYS_ID}},
            {self.KEYS_FIELD: []},
        ]
        self._send(operations)

    def delete_elastic_index(self) -> None:
        """Delete the whole index backing this dictionary. Use with caution."""
        self._es.indices.delete(index=self._index)


__all__ = [
    "DEFAULT_URL",
    "ENV_VAR",
    "ElasticDocDict",
    "KeyShouldBeStringException",
    "default_client",
]
