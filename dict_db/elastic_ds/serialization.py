"""Backwards-compatible alias for :mod:`dict_db.serialization`.

Kept so that ``from dict_db.<backend>.serialization import ...`` keeps working.
New code should import from :mod:`dict_db.serialization`.
"""

from dict_db.serialization import (
    JSONSerializer,
    PassThroughSerializer,
    PickleSerializer,
    decode_text,
)

__all__ = ["JSONSerializer", "PassThroughSerializer", "PickleSerializer", "decode_text"]
