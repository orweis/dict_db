"""Simple publish/subscribe message queues and an RPC-style API on top of them."""

from __future__ import annotations

import logging
import time
from types import TracebackType
from typing import Any, ClassVar

from ..serialization import JSONSerializer, PassThroughSerializer, PickleSerializer
from . import redis_config

__author__ = "OrW"

logger = logging.getLogger(__name__)


class MessageQueue(PassThroughSerializer):
    """Publish to and read from a list of Redis pub/sub channels.

    Reading requires entering the queue as a context manager::

        with MessageQueue(["events"]) as queue:
            message = queue.read()
    """

    def __init__(self, channels: list[str] | tuple[str, ...], redis_client: Any = None) -> None:
        if not isinstance(channels, (list, tuple)) or not all(
            isinstance(channel, (str, bytes)) for channel in channels
        ):
            raise TypeError("channels must be a list of channel names")
        self._redis_client = redis_client if redis_client is not None else redis_config.get_client()
        self._pub_sub = self._redis_client.pubsub()
        self._channels = list(channels)
        self._is_in_read_mode = False
        self._received_subscription = False

    @property
    def channels(self) -> list[str]:
        """The channels this queue publishes to and reads from."""
        return list(self._channels)

    def write(
        self,
        message: Any,
        wait_for_readers: bool = True,
        timeout: float | None = None,
        poll_interval: float = 0.01,
    ) -> None:
        """Publish ``message`` to every channel.

        :param wait_for_readers: re-publish until at least one subscriber
            received the message on each channel.
        :param timeout: with ``wait_for_readers``, give up after this many
            seconds and raise :class:`TimeoutError` (``None`` waits forever).
        :param poll_interval: seconds to sleep between publish attempts.
        """
        payload = self.serialize(message)
        deadline = None if timeout is None else time.monotonic() + timeout
        for channel in self._channels:
            while True:
                received = self._redis_client.publish(channel, payload)
                if received or not wait_for_readers:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"no reader received the message on channel {channel!r}")
                time.sleep(poll_interval)

    def read(
        self,
        block: bool = True,
        accept_old_messages: bool = False,
        timeout: float | None = None,
    ) -> Any:
        """Return the next message, or ``None`` if none is available.

        :param block: wait for a message. Without blocking, only messages
            already received are returned.
        :param accept_old_messages: accept messages that arrive before the
            subscription is confirmed.
        :param timeout: with ``block``, the maximum seconds to wait
            (``None`` waits forever).
        :raises RuntimeError: if called outside a ``with queue:`` block.
        """
        if not self._is_in_read_mode:
            raise RuntimeError("read() must be called inside a 'with queue:' block")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if not block:
                wait = 0.0
            elif deadline is None:
                wait = 1.0
            else:
                wait = max(0.0, deadline - time.monotonic())
            message = self._pub_sub.get_message(timeout=wait)
            if message is not None:
                if message["type"] == "subscribe":
                    self._received_subscription = True
                elif message["type"] == "message" and (
                    accept_old_messages or self._received_subscription
                ):
                    return self.deserialize(message["data"])
                continue
            if not block or (deadline is not None and time.monotonic() >= deadline):
                return None

    def __enter__(self) -> MessageQueue:
        self._pub_sub.subscribe(*self._channels)
        self._is_in_read_mode = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._pub_sub.unsubscribe()
        self._is_in_read_mode = False
        self._received_subscription = False

    def close(self) -> None:
        """Close the pub/sub connection."""
        self._pub_sub.close()


class PickleMessageQueue(MessageQueue, PickleSerializer):
    """Pickle messages.

    .. warning:: Anyone who can publish to the channels can execute arbitrary
       code in the reader. Only use on a trusted, access-controlled Redis.
    """


class JSONMessageQueue(MessageQueue, JSONSerializer):
    """Serialize messages as JSON."""


class QueueApi(JSONMessageQueue):
    """Call methods of this object from messages published on its channels.

    A message ``{"$name": "greet", "who": "world"}`` calls
    ``self.greet(who="world")``. Only *handler methods* can be called:

    * if :attr:`EXPOSED_METHODS` is set, only the names it lists;
    * otherwise, public methods defined by a subclass. Names starting with
      ``_`` and everything defined by :class:`QueueApi` and its bases (``run``,
      ``write``, ``read``, ...) are never callable.

    Messages come from anyone who can publish to the channels, so handlers
    must validate their arguments.
    """

    METHOD_NAME_KEY = "$name"
    #: Optional explicit allowlist of handler names.
    EXPOSED_METHODS: ClassVar[frozenset[str] | None] = None

    def __init__(self, channels: list[str] | tuple[str, ...], redis_client: Any = None) -> None:
        super().__init__(channels, redis_client=redis_client)

    def run(self, max_messages: int | None = None) -> None:
        """Read and dispatch messages forever (or ``max_messages`` messages).

        A message that fails (malformed, not allowed, or a handler error) is
        logged and does not stop the loop.
        """
        handled = 0
        with self:
            while max_messages is None or handled < max_messages:
                msg = self.read()
                handled += 1
                try:
                    self.message_to_call(msg)
                except Exception:
                    name = msg.get(self.METHOD_NAME_KEY) if isinstance(msg, dict) else None
                    logger.exception("Failed to handle incoming message (name=%r)", name)

    def is_exposed(self, name: Any) -> bool:
        """Return ``True`` if ``name`` may be called by an incoming message."""
        if not isinstance(name, str) or not name or name.startswith("_"):
            return False
        if self.EXPOSED_METHODS is not None:
            allowed = name in self.EXPOSED_METHODS
        else:
            allowed = name not in _QUEUE_API_RESERVED
        return allowed and callable(getattr(type(self), name, None))

    def message_to_call(self, msg: Any) -> Any:
        """Dispatch ``msg`` to its handler and return the handler's result.

        :raises ValueError: if the message is malformed.
        :raises KeyError: if the name does not map to an exposed handler.
        """
        if not isinstance(msg, dict) or self.METHOD_NAME_KEY not in msg:
            raise ValueError(f"incoming message must be a dict with a {self.METHOD_NAME_KEY!r} key")
        name = msg[self.METHOD_NAME_KEY]
        if not self.is_exposed(name):
            raise KeyError(f"incoming message name {name!r} does not map to an exposed method")
        kwargs = {k: v for k, v in msg.items() if k != self.METHOD_NAME_KEY}
        if not all(isinstance(k, str) for k in kwargs):
            raise ValueError("message argument names must be strings")
        return getattr(self, name)(**kwargs)


_QUEUE_API_RESERVED = frozenset(dir(QueueApi))

__all__ = ["JSONMessageQueue", "MessageQueue", "PickleMessageQueue", "QueueApi"]
