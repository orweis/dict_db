"""Dictionary interface to a whole Redis database (plain string keys).

:class:`RedisDict` maps directly onto top-level Redis keys: ``len()`` is the
size of the whole database and ``keys()`` lists every key in it. To keep a
dictionary inside a single Redis key use
:class:`~dict_db.redis_ds.redis_hash_dict.RedisHashDict`; for a namespaced set
of top-level keys use :class:`~dict_db.redis_ds.redis_path_dict.RedisPathDict`.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from typing import Any

from .._compat import DictMixin
from ..serialization import JSONSerializer, PassThroughSerializer, PickleSerializer, decode_text
from . import redis_config

_MISSING = object()


class RedisDict(DictMixin, PassThroughSerializer):
    """Dictionary interface to a Redis database."""

    def __init__(self, redis_client: Any = None) -> None:
        """
        :param redis_client: client used for all requests. Defaults to
            :func:`dict_db.redis_ds.redis_config.get_client`.
        """
        self._client = redis_client if redis_client is not None else redis_config.get_client()
        self._default_expiration: int | datetime.timedelta | None = None

    @property
    def client(self) -> Any:
        """The underlying Redis client."""
        return self._client

    def keys(self, pattern: str = "*") -> list[Any]:  # type: ignore[override]
        """Return the keys matching a Redis glob ``pattern`` (uses ``SCAN``)."""
        return [decode_text(key) for key in self._client.scan_iter(match=pattern)]

    def __iter__(self) -> Iterator[Any]:
        return iter(self.keys())

    def __len__(self) -> int:
        """Number of keys in the whole Redis database (``DBSIZE``)."""
        return int(self._client.dbsize())

    def __getitem__(self, key: Any) -> Any:
        """Return the value of ``key``; raise :class:`KeyError` if it is missing."""
        value = self._client.get(key)
        if value is None:
            raise KeyError(key)
        return self.deserialize(value)

    def increment_key(self, key: Any, value: int | float = 1) -> Any:
        """Atomically add ``value`` to a numeric key and return the new value."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"increment values should be numbers, not {type(value)}")
        if isinstance(value, int):
            return self._client.incrby(key, value)
        return self._client.incrbyfloat(key, value)

    def _set_command(self, client: Any, key: Any, val: Any) -> Any:
        """Issue the ``SET`` for ``key`` on ``client`` (a client or pipeline)."""
        expiration = self.default_expiration
        if isinstance(expiration, (int, datetime.timedelta)) and not isinstance(expiration, bool):
            return client.set(key, self.serialize(val), ex=expiration)
        return client.set(key, self.serialize(val))

    def __setitem__(self, key: Any, val: Any) -> None:
        """Set ``key`` (with the default expiration, if one is set)."""
        self._set_command(self._client, key, val)

    def __delitem__(self, key: Any) -> Any:
        """Ensure ``key`` does not exist.

        Unlike :class:`dict`, deleting a missing key is not an error; the
        number of deleted keys is returned.
        """
        return self._client.delete(key)

    def __contains__(self, key: object) -> bool:
        """Return ``True`` if ``key`` exists."""
        return bool(self._client.exists(key))

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value of ``key`` or ``default`` if it does not exist."""
        try:
            return self[key]
        except KeyError:
            return default

    def set_default_expiration(self, expiration: int | datetime.timedelta | None) -> None:
        """Expire newly set keys after ``expiration`` seconds (``None`` disables)."""
        self._default_expiration = expiration

    @property
    def default_expiration(self) -> int | datetime.timedelta | None:
        """Expiration (seconds) applied to keys on assignment, or ``None``."""
        return self._default_expiration

    def expire(self, key: Any, timeout: int | datetime.timedelta) -> Any:
        """Set a time-to-live of ``timeout`` seconds on ``key``."""
        return self._client.expire(key, timeout)


class PickleRedisDict(RedisDict, PickleSerializer):
    """Serialize values with pickle. Only use with a trusted Redis (see README)."""


class JSONRedisDict(RedisDict, JSONSerializer):
    """Serialize values as JSON."""


__all__ = ["JSONRedisDict", "PickleRedisDict", "RedisDict"]
