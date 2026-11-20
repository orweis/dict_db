"""A Pythonic interface to a Redis list."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from redis.exceptions import ResponseError

from ..serialization import JSONSerializer, PassThroughSerializer, PickleSerializer
from . import redis_config


class RedisList(PassThroughSerializer):
    """A list stored in one Redis list key."""

    def __init__(self, list_key: str, redis_client: Any = None) -> None:
        """
        :param list_key: the Redis key of the list.
        :param redis_client: client used for all requests. Defaults to
            :func:`dict_db.redis_ds.redis_config.get_client`.
        """
        self._client = redis_client if redis_client is not None else redis_config.get_client()
        self.list_key = list_key

    @property
    def client(self) -> Any:
        """The underlying Redis client."""
        return self._client

    def __len__(self) -> int:
        """Number of values in the list."""
        return int(self._client.llen(self.list_key))

    def __getitem__(self, key: int | slice) -> Any:
        """Return a value by index, or a list of values for a slice.

        Indexing and slicing follow Python semantics (negative indices,
        exclusive slice stop, steps).

        :raises IndexError: if an index is out of range.
        """
        if isinstance(key, slice):
            if key.step in (None, 1):
                start, stop, _ = key.indices(len(self))
                if stop <= start:
                    return []
                values = self._client.lrange(self.list_key, start, stop - 1)
            else:
                values = self._client.lrange(self.list_key, 0, -1)[key]
            return [self.deserialize(value) for value in values]
        if isinstance(key, int) and not isinstance(key, bool):
            value = self._client.lindex(self.list_key, key)
            if value is None:
                raise IndexError("RedisList index out of range")
            return self.deserialize(value)
        raise TypeError(f"RedisList indices must be integers or slices, not {type(key).__name__}")

    def __iter__(self) -> Iterator[Any]:
        for value in self._client.lrange(self.list_key, 0, -1):
            yield self.deserialize(value)

    def trim(self, start: int = 0, end: int = -1) -> Any:
        """Keep only the values between ``start`` and ``end`` (inclusive)."""
        return self._client.ltrim(self.list_key, start, end)

    def delete(self) -> None:
        """Delete the whole list."""
        self._client.delete(self.list_key)

    def __setitem__(self, pos: int, val: Any) -> None:
        """Set the value at index ``pos``.

        :raises IndexError: if ``pos`` is out of range.
        """
        try:
            self._client.lset(self.list_key, pos, self.serialize(val))
        except ResponseError as err:
            raise IndexError("RedisList assignment index out of range") from err

    def append(self, val: Any, head: bool = False) -> Any:
        """Append ``val`` to the tail (or the head if ``head`` is true)."""
        val = self.serialize(val)
        if head:
            return self._client.lpush(self.list_key, val)
        return self._client.rpush(self.list_key, val)

    def pop(self, head: bool = False, blocking: bool = False, timeout: float = 0) -> Any:
        """Remove and return a value from the tail (or head).

        :param head: pop from the head instead of the tail.
        :param blocking: wait for a value if the list is empty.
        :param timeout: with ``blocking``, the maximum seconds to wait
            (``0`` waits forever).
        :return: the value, or ``None`` if the list is empty / the wait timed out.
        """
        if blocking:
            command = self._client.blpop if head else self._client.brpop
            result = command([self.list_key], timeout=timeout)
            return None if result is None else self.deserialize(result[1])
        value = self._client.lpop(self.list_key) if head else self._client.rpop(self.list_key)
        return self.deserialize(value)

    def __repr__(self) -> str:
        """Represent the entire list."""
        return f"RedisList({list(self)!r})"


class PickleRedisList(RedisList, PickleSerializer):
    """Serialize values with pickle. Only use with a trusted Redis (see README)."""


class JSONRedisList(RedisList, JSONSerializer):
    """Serialize values as JSON."""


__all__ = ["JSONRedisList", "PickleRedisList", "RedisList"]
