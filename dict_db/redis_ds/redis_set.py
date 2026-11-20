"""A Pythonic interface to a Redis set."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ..serialization import JSONSerializer, PassThroughSerializer, PickleSerializer
from . import redis_config


class RedisSet(PassThroughSerializer):
    """An object which behaves like a Python set, but is backed by Redis."""

    def __init__(self, set_key: str, redis_client: Any = None) -> None:
        """
        :param set_key: the Redis key of the set.
        :param redis_client: client used for all requests. Defaults to
            :func:`dict_db.redis_ds.redis_config.get_client`.
        """
        self._client = redis_client if redis_client is not None else redis_config.get_client()
        self.set_key = set_key

    @property
    def client(self) -> Any:
        """The underlying Redis client."""
        return self._client

    def __len__(self) -> int:
        """Number of values in the set."""
        return int(self._client.scard(self.set_key))

    def __iter__(self) -> Iterator[Any]:
        for item in self._client.sscan_iter(self.set_key):
            yield self.deserialize(item)

    def delete_all(self) -> None:
        """Delete the whole set."""
        self._client.delete(self.set_key)

    def add(self, val: Any) -> None:
        """Add a value to the set."""
        self._client.sadd(self.set_key, self.serialize(val))

    def update(self, vals: Iterable[Any]) -> None:
        """Add multiple values to the set (an empty iterable is a no-op)."""
        serialized = [self.serialize(x) for x in vals]
        if serialized:
            self._client.sadd(self.set_key, *serialized)

    def __contains__(self, val: object) -> bool:
        """Return ``True`` if ``val`` is a member of the set."""
        return bool(self._client.sismember(self.set_key, self.serialize(val)))

    def pop(self) -> Any:
        """Remove and return an arbitrary value, or ``None`` if the set is empty."""
        return self.deserialize(self._client.spop(self.set_key))

    def remove(self, val: Any) -> None:
        """Remove ``val`` from the set (missing values are not an error)."""
        self._client.srem(self.set_key, self.serialize(val))

    def __repr__(self) -> str:
        """Represent all members of the set."""
        objs = [self.deserialize(x) for x in self._client.smembers(self.set_key)]
        return f"RedisSet({objs!r})"


class PickleRedisSet(RedisSet, PickleSerializer):
    """Serialize values with pickle. Only use with a trusted Redis (see README)."""


class JSONRedisSet(RedisSet, JSONSerializer):
    """Serialize values as JSON."""


__all__ = ["JSONRedisSet", "PickleRedisSet", "RedisSet"]
