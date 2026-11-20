"""Serializer mixins shared by the Redis and Elasticsearch data structures.

A data structure class combines a backend class (for example
:class:`~dict_db.redis_ds.redis_hash_dict.RedisHashDict`) with one of the
serializer mixins below. The mixin decides how Python values are turned into
what is stored in the database and back.

.. warning::

   :class:`PickleSerializer` calls :func:`pickle.loads` on data read from the
   database. Anyone who can write to that database (or publish to a pub/sub
   channel, for the message queues) can execute arbitrary code in every
   process that reads the value. Only use the ``Pickle*`` classes against a
   database that is fully trusted, authenticated and not shared. Prefer the
   ``JSON*`` classes.
"""

from __future__ import annotations

import json
import pickle
from typing import Any


def decode_text(value: Any) -> Any:
    """Return ``value`` decoded as UTF-8 text when it is ``bytes``.

    redis-py returns ``bytes`` for keys, members and values unless the client
    was created with ``decode_responses=True``. Values that are not valid UTF-8
    are returned unchanged.
    """
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(value)
    return value


class PassThroughSerializer:
    """Store values as-is.

    Values are handed to the client unchanged (redis-py accepts ``str``,
    ``bytes``, ``int`` and ``float``). Values read back are decoded to ``str``
    when they are valid UTF-8, so numbers come back as strings.
    """

    def serialize(self, obj: Any) -> Any:
        """Return ``obj`` unchanged."""
        return obj

    def deserialize(self, obj: Any) -> Any:
        """Return ``obj`` decoded to ``str`` when possible."""
        return decode_text(obj)


class PickleSerializer(PassThroughSerializer):
    """Serialize values with :mod:`pickle`.

    .. warning::

       Deserializing runs :func:`pickle.loads` on data read from the
       database, which allows arbitrary code execution by anyone able to
       write to it. Use only with a trusted, access-controlled database.
       The client must not use ``decode_responses=True``.
    """

    def serialize(self, obj: Any) -> bytes:
        """Pickle ``obj``."""
        return pickle.dumps(obj)

    def deserialize(self, obj: Any) -> Any:
        """Unpickle ``obj`` (``None`` is returned unchanged)."""
        if obj is None:
            return None
        return pickle.loads(obj)  # noqa: S301 - documented, opt-in by class choice


class JSONSerializer(PassThroughSerializer):
    """Serialize values as JSON.

    For backwards compatibility with 1.x, serialization is lenient: objects
    that JSON cannot represent are stored as ``null`` and dictionary keys that
    are not ``str``/``int``/``float``/``bool``/``None`` are skipped. Values
    that cannot be decoded are returned as a :class:`LoadFailure` instead of
    raising.
    """

    class LoadFailure:
        """Returned by :meth:`deserialize` when stored data is not valid JSON."""

        def __init__(self, value: Any, err: Exception) -> None:
            self.value = value
            self.err = err

        def __repr__(self) -> str:
            return f"LoadFailure(value={self.value!r}, err={self.err!r})"

    @staticmethod
    def default_none(obj: Any) -> None:
        """``json.dumps`` fallback: store unserializable objects as ``null``."""
        return None

    def serialize(self, obj: Any) -> str:
        """Dump ``obj`` to a JSON string."""
        return json.dumps(obj, skipkeys=True, default=self.default_none)

    def deserialize(self, obj: Any) -> Any:
        """Load a JSON value, or return a :class:`LoadFailure` if it is invalid."""
        if obj is None:
            return None
        try:
            return json.loads(obj)
        except (TypeError, ValueError) as err:
            return self.LoadFailure(obj, err)


__all__ = [
    "JSONSerializer",
    "PassThroughSerializer",
    "PickleSerializer",
    "decode_text",
]
