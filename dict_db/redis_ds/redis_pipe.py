"""A Redis client whose ``with`` block groups commands into a transaction."""

from __future__ import annotations

import threading
from types import TracebackType
from typing import Any

from redis import Redis

__author__ = "OrW"

# Attributes that always resolve on the client itself, even inside a transaction.
_OWN_ATTRIBUTES = frozenset(
    {
        "_pipe_local",
        "_local_state",
        "pipeline",
        "transaction_results",
        "in_transaction",
    }
)


class RedisPipe(Redis):
    """A :class:`redis.Redis` client usable as a transaction context manager.

    Inside ``with client:`` every command issued *in the current thread* is
    queued on a ``MULTI``/``EXEC`` pipeline, which is executed when the block
    exits normally. If the block raises, the queued commands are discarded.
    Results of the last transaction are available from
    :attr:`transaction_results`.

    Note that commands inside the block return the pipeline, not a value, so
    reads inside a transaction are not useful.

    All constructor arguments are passed to :class:`redis.Redis`, so host,
    port, password, ``ssl=True`` and so on can be configured, and
    :meth:`redis.Redis.from_url` works as well::

        client = RedisPipe.from_url("rediss://user:secret@redis.example:6380/0")
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        object.__setattr__(self, "_pipe_local", threading.local())
        super().__init__(*args, **kwargs)

    def __getattribute__(self, name: str) -> Any:
        if name in _OWN_ATTRIBUTES or name.startswith("__"):
            return super().__getattribute__(name)
        try:
            local = object.__getattribute__(self, "_pipe_local")
        except AttributeError:
            return super().__getattribute__(name)
        pipe = getattr(local, "pipe", None)
        if pipe is not None:
            return getattr(pipe, name)
        return super().__getattribute__(name)

    def _local_state(self) -> threading.local:
        return object.__getattribute__(self, "_pipe_local")

    @property
    def in_transaction(self) -> bool:
        """``True`` while the current thread is inside a ``with`` block."""
        return getattr(self._local_state(), "pipe", None) is not None

    def __enter__(self) -> RedisPipe:
        local = self._local_state()
        depth = getattr(local, "depth", 0)
        if depth == 0:
            local.pipe = self.pipeline()
        local.depth = depth + 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        local = self._local_state()
        local.depth -= 1
        if local.depth > 0:
            # Nested block: the outermost block executes the transaction.
            return
        pipe = local.pipe
        local.pipe = None
        try:
            if exc_type is None:
                local.results = pipe.execute()
            else:
                pipe.reset()
        finally:
            local.depth = 0

    @property
    def transaction_results(self) -> list[Any] | None:
        """Results returned by the last transaction executed in this thread."""
        return getattr(self._local_state(), "results", None)


__all__ = ["RedisPipe"]
