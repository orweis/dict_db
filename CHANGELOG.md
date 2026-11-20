# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [2.0.0] - Unreleased

A major release: the code base was ported from Python 2 to Python 3 and to
current Redis/Elasticsearch clients, with security and correctness fixes. See
"Migrating from 1.x" in the README.

### Breaking changes

- Python 2 support dropped; Python 3.10+ is required. Dependencies are declared
  as extras: `redis>=5,<9` (`dict_db[redis]`) and `elasticsearch>=8,<10`
  (`dict_db[elastic]`).
- Keys returned by the Redis data structures are `str` (redis-py 3+ returns
  `bytes`); values of the pass-through classes are decoded to `str` when they
  are valid UTF-8.
- `ExpirableRedisHashDict` (and its JSON/Pickle variants) store expiration
  timestamps as plain numbers instead of pickles. Existing Python 2 pickled
  metadata is still parsed safely (never unpickled); other unrecognised
  metadata is ignored with a warning.
- `ElasticDocDict` targets Elasticsearch 8/9: `doc_type` is now part of the
  index name (`<index>-<doc_type>`), the key list is stored as an array field
  updated with Painless scripts, `__ElasticDocDict_Keys` is a reserved key,
  non-`str` keys raise `KeyShouldBeStringException` (also under `python -O`),
  deleting a missing key raises `KeyError`, and the constructor no longer
  writes to the cluster.
- `RedisDict` / `RedisPathDict`: `d[missing]` raises `KeyError` instead of
  returning `None`.
- `RedisPathDict.keys()` returns logical keys (optionally filtered by a glob
  pattern) instead of full Redis paths.
- `RedisList`: out-of-range indices raise `IndexError` (they returned `None`),
  non-integer indices raise `TypeError`, and slices follow Python semantics
  (the stop index is exclusive; steps and negative indices work).
- `QueueApi` only dispatches to public handler methods defined by the subclass
  (or to the names in `EXPOSED_METHODS`); malformed messages raise `ValueError`
  instead of `AssertionError`.
- `MessageQueue(channels)` raises `TypeError` for invalid channels and `read()`
  raises `RuntimeError` outside a `with` block (both were `assert`s).
  `read(block=False)` now returns an already-received message instead of always
  returning `None`.
- `RedisPipe`: a transaction whose `with` block raises is discarded instead of
  executed.
- `DictDbFactory` raises `ValueError` for unknown database or data structure
  types instead of returning `None`.
- `RedisHashDict.iteritems_cursor()` yields deserialized `(key, value)` items
  and stops at the end of the scan.
- The in-package `tests.py` modules were removed (tests now live in `tests/`).

### Security

- Fixed arbitrary code execution through pickle in the "JSON" expirable hash
  dicts: `ExpirableJSONRedisHashDict` unpickled its expiration metadata from
  Redis.
- `QueueApi` no longer lets pub/sub messages call arbitrary attributes (`run`,
  `write`, private and dunder methods); a failing message no longer stops the
  `run()` loop.
- `Pickle*` classes are documented as unsafe for untrusted data; JSON is the
  recommended serializer.
- Connections are configurable (URL, auth, TLS) and created lazily instead of
  an unconfigurable client at import time.
- Redis `KEYS` replaced by `SCAN`; glob characters in a `RedisPathDict` path can
  no longer match other namespaces.
- `assert`-based validation replaced by explicit exceptions.

### Fixed

- `RedisHashDict.upsert()` discarded the new data.
- `RedisDict` default expiration used the redis-py 2 `setex` argument order.
- `RedisDict.get()` / `RedisPathDict.get()` returned the default for stored
  falsy values (`0`, `""`, `False`, `[]`).
- `ExpirableRedisHashDict` ignored an injected `redis_client`, left expiration
  metadata behind after deletes, kept a stale expiration when a key was
  re-assigned, and `get()` returned expired values.
- `RedisPathDict.delete_all()` did not delete the stored values.
- `RedisSet.update([])` raised; `__contains__` methods return `bool`.
- `RedisList.pop(blocking=True)` gained a `timeout` and returns `None` on timeout.
- `MessageQueue.write()` can time out (`timeout=`) instead of spinning forever,
  and no longer busy-waits.
- `RedisPipe` supports nested `with` blocks, is per-thread, stores
  `transaction_results`, and resets itself if the transaction fails.
- `from dict_db import DictDbFactory, Consts` works on Python 3; importing
  `dict_db` no longer requires both Redis and Elasticsearch clients.

### Added

- `pyproject.toml` packaging (`dict_db.__version__`), type hints and `py.typed`.
- `redis_config.get_client()` / `set_client()` and the `DICT_DB_REDIS_URL` /
  `DICT_DB_ELASTIC_URL` environment variables; `DictDbFactory(..., client=...)`.
- A single `dict_db.serialization` module (the per-backend `serialization`
  modules remain as aliases).
- `ElasticDocDict(refresh=...)`, `flush()` and `index_name`.
- pytest suite using fakeredis and a fake Elasticsearch client, GitHub Actions
  CI (ruff, mypy, pytest on Python 3.10-3.14, build, pip-audit), Dependabot,
  `SECURITY.md` and `CONTRIBUTING.md`.

## [1.1] - 2016

- Last Python 2 version (the version string lived in `dict_db.redis_ds`).
