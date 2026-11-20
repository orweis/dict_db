"""Internal helpers shared by the data structures."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from typing import Any


class DictMixin(MutableMapping):
    """:class:`collections.abc.MutableMapping` plus the 1.x (Python 2 era) API.

    Subclasses implement ``__getitem__``, ``__setitem__``, ``__delitem__``,
    ``__iter__`` and ``__len__``. This mixin keeps ``iterkeys``,
    ``itervalues``, ``iteritems`` and ``has_key`` available so code written
    against dict_db 1.x keeps working.
    """

    def iterkeys(self) -> Iterator[Any]:
        """Iterate over keys (alias of ``iter(self)``)."""
        return iter(self)

    def itervalues(self) -> Iterator[Any]:
        """Iterate over values."""
        for _key, value in self.iteritems():
            yield value

    def iteritems(self) -> Iterator[tuple[Any, Any]]:
        """Iterate over ``(key, value)`` pairs."""
        for key in self:
            try:
                yield key, self[key]
            except KeyError:
                # The key disappeared (deleted or expired) while iterating.
                continue

    def has_key(self, key: Any) -> bool:
        """Return ``key in self`` (1.x compatibility)."""
        return key in self

    def __repr__(self) -> str:
        return repr(dict(self.iteritems()))
