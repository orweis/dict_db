"""Dictionary interface to a single Redis hash."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from typing import Any

from .._compat import DictMixin
from ..serialization import JSONSerializer, PassThroughSerializer, PickleSerializer, decode_text
from . import redis_config

logger = logging.getLogger(__name__)


class RedisHashDict(DictMixin, PassThroughSerializer):
    """A dictionary stored in one Redis hash (``HSET``/``HGET``)."""

    def __init__(self, hash_key: str, redis_client: Any = None) -> None:
        """
        :param hash_key: the Redis key of the hash.
        :param redis_client: client used for all requests. Defaults to
            :func:`dict_db.redis_ds.redis_config.get_client`.
        """
        self._client = redis_client if redis_client is not None else redis_config.get_client()
        self.hash_key = hash_key

    @property
    def client(self) -> Any:
        """The underlying Redis client."""
        return self._client

    def keys(self) -> list[Any]:  # type: ignore[override]
        """Return all keys in the hash."""
        return [decode_text(key) for key in self._client.hkeys(self.hash_key)]

    def iteritems(self) -> Iterator[tuple[Any, Any]]:
        """Iterate over ``(key, value)`` pairs using ``HSCAN``."""
        for key, value in self._client.hscan_iter(self.hash_key):
            yield decode_text(key), self.deserialize(value)

    def iteritems_cursor(self, cursor: int | str = 0) -> Iterator[tuple[int, tuple[Any, Any]]]:
        """Like :meth:`iteritems`, but also yield the ``HSCAN`` cursor.

        Each item is ``(cursor, (key, value))`` where ``cursor`` is the cursor
        to pass back to resume iteration after the current batch (``0`` once
        the scan is complete).
        """
        cursor = int(cursor)
        while True:
            cursor, data = self._client.hscan(self.hash_key, cursor=cursor)
            cursor = int(cursor)
            for key, value in data.items():
                yield cursor, (decode_text(key), self.deserialize(value))
            if cursor == 0:
                return

    def __iter__(self) -> Iterator[Any]:
        for key, _value in self._client.hscan_iter(self.hash_key):
            yield decode_text(key)

    def __len__(self) -> int:
        """Number of fields in the hash."""
        return int(self._client.hlen(self.hash_key))

    def __getitem__(self, key: Any) -> Any:
        """Return the value of ``key``; raise :class:`KeyError` if it is missing."""
        value = self._client.hget(self.hash_key, key)
        if value is None:
            raise KeyError(key)
        return self.deserialize(value)

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value of ``key`` or ``default`` if it does not exist."""
        value = self._client.hget(self.hash_key, key)
        if value is None:
            return default
        return self.deserialize(value)

    def increment_key(self, key: Any, value: int | float = 1) -> Any:
        """Atomically add ``value`` to a numeric field and return the new value."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"increment values should be numbers, not {type(value)}")
        if isinstance(value, int):
            return self._client.hincrby(self.hash_key, key, value)
        return self._client.hincrbyfloat(self.hash_key, key, value)

    def __setitem__(self, key: Any, val: Any) -> None:
        """Set ``key`` in the hash."""
        self._client.hset(self.hash_key, key, self.serialize(val))

    def upsert(self, key: Any, data: dict[Any, Any]) -> None:
        """Merge ``data`` into the dict stored at ``key`` (creating it if needed).

        This is a read-modify-write and is not atomic across processes.
        """
        current = self.get(key)
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(data)
        self[key] = merged

    def __delitem__(self, key: Any) -> Any:
        """Ensure ``key`` is not in the hash.

        Deleting a missing key is not an error; the number of removed fields is
        returned.
        """
        return self._client.hdel(self.hash_key, key)

    def delete_all(self) -> None:
        """Delete the whole hash."""
        self._client.delete(self.hash_key)

    def __contains__(self, key: object) -> bool:
        """Return ``True`` if ``key`` is in the hash."""
        return bool(self._client.hexists(self.hash_key, key))


class PickleRedisHashDict(RedisHashDict, PickleSerializer):
    """Serialize values with pickle. Only use with a trusted Redis (see README)."""


class JSONRedisHashDict(RedisHashDict, JSONSerializer):
    """Serialize values as JSON."""


# dict_db 1.x stored expiration timestamps with Python 2 ``cPickle`` (protocol
# 0). Those payloads are parsed with these patterns instead of being unpickled.
_LEGACY_PICKLED_FLOAT = re.compile(rb"^F([-+0-9.eE]+|inf|-inf|nan)\n\.$")
_LEGACY_PICKLED_INT = re.compile(rb"^I(-?[0-9]+)\n\.$")
_LEGACY_PICKLED_NONE = b"N."


def _parse_expiration(raw: Any) -> float | None:
    """Parse a stored expiration timestamp without ever unpickling it."""
    if raw is None:
        return None
    data = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
    try:
        return float(data)
    except ValueError:
        pass
    if data == _LEGACY_PICKLED_NONE:
        return None
    match = _LEGACY_PICKLED_FLOAT.match(data) or _LEGACY_PICKLED_INT.match(data)
    if match:
        return float(match.group(1))
    logger.warning("Ignoring unrecognised expiration metadata %r", data[:64])
    return None


class ExpirableRedisHashDict(RedisHashDict):
    """A :class:`RedisHashDict` whose keys can expire individually.

    Expiration timestamps (seconds since the epoch) are stored as plain
    numbers in a separate hash named ``meta_<hash_key>|expiration``. Expired
    keys are removed lazily when they are read; ``len()``, :meth:`keys` and
    iteration include keys that have expired but were not read yet. Use
    :meth:`iter_fresh_items` to skip them.
    """

    class KeyExpiredError(KeyError):
        """Raised by ``__getitem__`` when the key exists but has expired."""

    def __init__(self, hash_key: str, redis_client: Any = None) -> None:
        super().__init__(hash_key, redis_client=redis_client)
        self._default_expiration: float | None = None
        self._expiration_key = f"meta_{hash_key}|expiration"

    @property
    def expiration_key(self) -> str:
        """Redis key of the hash holding the expiration timestamps."""
        return self._expiration_key

    def set_default_expiration(self, expiration: float | None) -> None:
        """Expire keys ``expiration`` seconds after assignment (``None`` disables)."""
        self._default_expiration = expiration

    @property
    def default_expiration(self) -> float | None:
        """Expiration (seconds) applied on assignment, or ``None``."""
        return self._default_expiration

    def iter_fresh_items(self) -> Iterator[tuple[Any, Any]]:
        """Iterate over ``(key, value)`` pairs that have not expired."""
        now = time.time()
        expirations = {
            decode_text(k): _parse_expiration(v)
            for k, v in self._client.hgetall(self._expiration_key).items()
        }
        for key, value in self.iteritems():
            expiration = expirations.get(key)
            if expiration is None or now <= expiration:
                yield key, value

    def always_get(self, key: Any) -> Any:
        """Return the value of ``key`` ignoring its expiration."""
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        """Return ``True`` if ``key`` exists and has not expired."""
        if self.should_expire(key):
            return False
        return super().__contains__(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        """Set ``key``; its expiration is reset to the default expiration."""
        self.set(key, value, timeout=self._default_expiration)

    def set(self, key: Any, value: Any, timeout: float | None = None) -> None:
        """Set ``key`` to expire after ``timeout`` seconds (``None``: never)."""
        super().__setitem__(key, value)
        self.expire(key, timeout=timeout)

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value of ``key``, or ``default`` if missing or expired."""
        try:
            return self[key]
        except KeyError:
            return default

    def get_expiration(self, key: Any) -> float | None:
        """Return the expiration timestamp of ``key`` or ``None``."""
        return _parse_expiration(self._client.hget(self._expiration_key, key))

    def get_expiration_as_text(self, key: Any) -> str:
        """Return the expiration of ``key`` as text (``"Never"`` if none)."""
        expiration = self.get_expiration(key)
        if expiration is None:
            return "Never"
        return time.ctime(expiration)

    def should_expire(self, key: Any) -> bool:
        """Return ``True`` if ``key`` has an expiration in the past."""
        expiration = self.get_expiration(key)
        return expiration is not None and time.time() > expiration

    def __getitem__(self, key: Any) -> Any:
        """Return the value of ``key``.

        :raises KeyExpiredError: if the key has expired (it is deleted).
        :raises KeyError: if the key does not exist.
        """
        if self.should_expire(key):
            del self[key]
            raise self.KeyExpiredError(key)
        return super().__getitem__(key)

    def __delitem__(self, key: Any) -> Any:
        """Ensure ``key`` and its expiration are removed."""
        self._client.hdel(self._expiration_key, key)
        return super().__delitem__(key)

    def delete_all(self) -> None:
        """Delete the hash and its expiration metadata."""
        self._client.delete(self.hash_key, self._expiration_key)

    def expire(self, key: Any, timeout: float | None) -> None:
        """Expire ``key`` in ``timeout`` seconds, or never if ``timeout`` is ``None``."""
        if timeout is None:
            self._client.hdel(self._expiration_key, key)
        else:
            self._client.hset(self._expiration_key, key, repr(float(timeout) + time.time()))


class ExpirablePickleRedisHashDict(ExpirableRedisHashDict, PickleSerializer):
    """Expirable hash dict with pickled values. Only use with a trusted Redis."""


class ExpirableJSONRedisHashDict(ExpirableRedisHashDict, JSONSerializer):
    """Expirable hash dict with JSON values."""


__all__ = [
    "ExpirableJSONRedisHashDict",
    "ExpirablePickleRedisHashDict",
    "ExpirableRedisHashDict",
    "JSONRedisHashDict",
    "PickleRedisHashDict",
    "RedisHashDict",
]
