"""A dictionary of top-level Redis keys sharing a common path prefix."""

from __future__ import annotations

import contextlib
import fnmatch
from collections.abc import Iterator
from typing import Any

from ..serialization import decode_text
from .redis_dict import RedisDict
from .redis_pipe import RedisPipe
from .redis_set import RedisSet

__author__ = "OrW"


class RedisPathDict(RedisDict):
    """Store each item as its own Redis key, ``PathDict|<path>|<key>``.

    The logical keys are tracked in the set ``meta_PathDict|<path>|keys`` so
    ``len()``, iteration and :meth:`keys` do not need to scan the database.
    Unlike a hash, every item can have its own Redis TTL (see :meth:`expire`).
    """

    def __init__(self, path: str, redis_client: Any = None) -> None:
        super().__init__(redis_client=redis_client)
        self._path = path
        self._keys = RedisSet(self._build_path("keys", prefix="meta_"), redis_client=self._client)

    @property
    def path(self) -> str:
        """The path (namespace) of this dictionary."""
        return self._path

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[Any]:
        """Yield something to queue commands on, executed atomically on exit."""
        if isinstance(self._client, RedisPipe):
            with self._client:
                yield self._client
        else:
            pipe = self._client.pipeline()
            yield pipe
            pipe.execute()

    def keys(self, pattern: str = "*") -> list[Any]:  # type: ignore[override]
        """Return the logical keys matching a glob ``pattern``."""
        keys = list(self._keys)
        if pattern == "*":
            return keys
        return [key for key in keys if fnmatch.fnmatchcase(str(key), pattern)]

    def delete_all(self) -> None:
        """Delete every item of this dictionary and its key index."""
        paths = [self._build_path(key) for key in self._keys]
        with self._transaction() as client:
            if paths:
                client.delete(*paths)
            client.delete(self._keys.set_key)

    def __len__(self) -> int:
        return len(self._keys)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._keys)

    def _build_path(self, key: Any, prefix: str | None = None) -> str:
        return f"{prefix or ''}PathDict|{self.path}|{decode_text(key)}"

    def __getitem__(self, key: Any) -> Any:
        """Return the value of ``key``; raise :class:`KeyError` if it is missing."""
        try:
            return super().__getitem__(self._build_path(key))
        except KeyError:
            raise KeyError(key) from None

    def __setitem__(self, key: Any, val: Any) -> None:
        """Set ``key`` and record it in the key index atomically."""
        path = self._build_path(key)
        with self._transaction() as client:
            client.sadd(self._keys.set_key, self._keys.serialize(key))
            self._set_command(client, path, val)

    def __delitem__(self, key: Any) -> None:
        """Ensure ``key`` is deleted (missing keys are not an error)."""
        path = self._build_path(key)
        with self._transaction() as client:
            client.srem(self._keys.set_key, self._keys.serialize(key))
            client.delete(path)

    def __contains__(self, key: object) -> bool:
        """Return ``True`` if ``key`` exists."""
        return super().__contains__(self._build_path(key))

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value of ``key`` or ``default``."""
        # RedisDict.get calls self[key], which builds the path.
        return super().get(key, default=default)

    def expire(self, key: Any, timeout: Any) -> Any:
        """Set a Redis time-to-live on ``key``.

        Note that the key stays in the key index after Redis expires it.
        """
        return super().expire(self._build_path(key), timeout)


__all__ = ["RedisPathDict"]
