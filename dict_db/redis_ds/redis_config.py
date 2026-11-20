"""Default Redis client used by the data structures.

The default client is created lazily, on first use, from the
``DICT_DB_REDIS_URL`` environment variable (default
``redis://localhost:6379/0``). No connection is opened at import time.

Configure it in one of these ways (from most to least explicit):

* pass ``redis_client=...`` to each data structure,
* call :func:`set_client` once at start-up,
* set ``DICT_DB_REDIS_URL`` (for example ``rediss://user:pass@host:6380/0``
  for TLS with authentication),
* assign ``dict_db.redis_ds.redis_config.CLIENT`` (1.x style monkey patch).
"""

from __future__ import annotations

import os
import threading
from typing import Any

from .redis_pipe import RedisPipe

ENV_VAR = "DICT_DB_REDIS_URL"
DEFAULT_URL = "redis://localhost:6379/0"

_lock = threading.Lock()


def get_client() -> Any:
    """Return the default client, creating it on first use."""
    client = globals().get("CLIENT")
    if client is not None:
        return client
    with _lock:
        client = globals().get("CLIENT")
        if client is None:
            client = RedisPipe.from_url(os.environ.get(ENV_VAR, DEFAULT_URL))
            globals()["CLIENT"] = client
    return client


def set_client(client: Any) -> None:
    """Replace the default client (``None`` resets it to lazy creation)."""
    globals()["CLIENT"] = client


def __getattr__(name: str) -> Any:
    # Keeps ``redis_config.CLIENT`` working without connecting at import time.
    if name == "CLIENT":
        return get_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["DEFAULT_URL", "ENV_VAR", "get_client", "set_client"]
