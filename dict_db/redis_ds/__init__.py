"""Redis data structures (dict, hash dict, path dict, list, set, message queue).

Based on a fork of https://github.com/lethain/Redis-Python-Datastructures.
Requires the ``redis`` extra: ``pip install "dict_db[redis]"``.
"""

from .. import __version__

__all__ = [
    "__version__",
    "message_queue",
    "redis_config",
    "redis_dict",
    "redis_hash_dict",
    "redis_list",
    "redis_path_dict",
    "redis_pipe",
    "redis_set",
]
