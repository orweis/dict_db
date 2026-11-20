DictDb
======
| "Work with DBs as if they are Python dictionaries"
| Database as dict
| Python Database interface

``dict_db`` wraps Redis and Elasticsearch in Python ``dict``, ``list`` and
``set`` interfaces, so code like ``db["key"] = value`` reads and writes the
database directly.

.. contents::
   :local:
   :depth: 1

Requirements
------------

* Python 3.10 or newer
* For Redis: a Redis server and ``redis`` (redis-py) 5.x to 8.x
* For Elasticsearch: an Elasticsearch 8.x/9.x server and ``elasticsearch``
  (elasticsearch-py) 8.x or 9.x, matching the server's major version

Install
-------

The package is not published to PyPI; install it from a checkout (or a Git
URL) with the extras for the back-ends you need:

.. code:: bash

    pip install ".[redis]"      # Redis data structures
    pip install ".[elastic]"    # Elasticsearch data structures
    pip install ".[all]"        # both

Quick start
-----------

.. code:: python

    >>> from dict_db import Consts, DictDbFactory
    >>> # Redis: a JSON-serialised hash stored at the key "test_sample"
    >>> db = DictDbFactory(Consts.DB_REDIS).create("test", "sample")
    >>> db["1"] = "Hello Db!"
    >>> db
    {'1': 'Hello Db!'}
    >>> type(db)
    <class 'dict_db.redis_ds.redis_hash_dict.JSONRedisHashDict'>
    >>> # Elasticsearch: one document per key in the index "test-sample"
    >>> db = DictDbFactory(Consts.DB_ELASTIC).create("test", "sample")
    >>> db["1"] = "Hello Db!"
    >>> db
    {'1': 'Hello Db!'}

``DictDbFactory(db_type, default_ds_type=Consts.DS_DICT, client=None)``
creates data structures with ``create(path, name, ds_type=None)``:

=====================  ==========================  ===========================================
``db_type``            ``ds_type``                 Result
=====================  ==========================  ===========================================
``Consts.DB_REDIS``    ``Consts.DS_DICT``          ``JSONRedisHashDict("<path>_<name>")``
``Consts.DB_REDIS``    ``Consts.DS_LIST``          ``JSONRedisList("<path>_<name>")``
``Consts.DB_ELASTIC``  ``Consts.DS_DICT``          ``ElasticDocDict(index=path, doc_type=name)``
``Consts.DB_ELASTIC``  ``Consts.DS_LIST``          ``NotImplementedError``
=====================  ==========================  ===========================================

Unknown database or data structure types raise ``ValueError``.

Connecting
----------

No connection is opened at import time. Each data structure accepts a client
(``redis_client=`` for Redis, ``es=`` for Elasticsearch, or ``client=`` on the
factory). Without one, a default client is created on first use from an
environment variable:

=========================  ================================  ====================================
Variable                   Default                           Example
=========================  ================================  ====================================
``DICT_DB_REDIS_URL``      ``redis://localhost:6379/0``      ``rediss://user:secret@host:6380/0``
``DICT_DB_ELASTIC_URL``    ``http://localhost:9200``         ``https://user:secret@host:9200``
=========================  ================================  ====================================

.. code:: python

    from elasticsearch import Elasticsearch
    from dict_db.redis_ds import redis_config
    from dict_db.redis_ds.redis_pipe import RedisPipe
    from dict_db.redis_ds.redis_hash_dict import JSONRedisHashDict
    from dict_db.elastic_ds.doc_dict import ElasticDocDict

    # Redis with TLS and authentication, set once for the whole process
    redis_config.set_client(RedisPipe.from_url("rediss://app:secret@redis.example:6380/0"))

    # ...or per data structure
    users = JSONRedisHashDict("users", redis_client=RedisPipe(host="localhost", port=6379))

    # Elasticsearch with an API key
    es = Elasticsearch("https://search.example:9200", api_key="...")
    docs = ElasticDocDict("app", "settings", es=es)

Use ``RedisPipe`` (a ``redis.Redis`` subclass) rather than a plain
``redis.Redis`` if you want ``with client:`` transactions (see below). Do not
use ``decode_responses=True`` with the ``Pickle*`` classes.

Data structures
---------------

Most classes come in three variants that differ only in how values are
serialised: the plain class (values stored as-is and read back as ``str``),
``JSON*`` (recommended) and ``Pickle*`` (see `Security`_).

Redis (``dict_db.redis_ds``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

==============================================  ==============================================================
Class                                           Stored as
==============================================  ==============================================================
``redis_hash_dict.RedisHashDict``               one Redis hash; also ``upsert``, ``increment_key``,
                                                ``iteritems_cursor``, ``delete_all``
``redis_hash_dict.ExpirableRedisHashDict``      a hash plus per-key expiration timestamps stored in
                                                ``meta_<hash_key>|expiration``; ``set(key, value, timeout)``,
                                                ``set_default_expiration``, ``iter_fresh_items``
``redis_path_dict.RedisPathDict``               one top-level key per item (``PathDict|<path>|<key>``) with
                                                a key index set, so each item can have its own Redis TTL
``redis_dict.RedisDict``                        the whole Redis database: ``len()`` is ``DBSIZE``
``redis_list.RedisList``                        a Redis list; Python indexing and slicing, ``append``,
                                                ``pop(head=False, blocking=False, timeout=0)``, ``trim``
``redis_set.RedisSet``                          a Redis set; ``add``, ``update``, ``remove``, ``pop``, ``in``
``message_queue.MessageQueue``                  pub/sub channels; ``write`` and ``read`` inside ``with queue:``
``message_queue.QueueApi``                      calls handler methods from pub/sub messages
==============================================  ==============================================================

Notes:

* The dictionaries implement ``collections.abc.MutableMapping``, so ``items()``,
  ``values()``, ``update()``, ``pop()``, ``setdefault()`` and ``==`` work. The 1.x
  helpers ``iteritems()``, ``iterkeys()``, ``itervalues()`` and ``has_key()`` are
  kept.
* ``del d[key]`` on a missing key is *not* an error for the Redis dictionaries
  (it was documented as "ensure deletion" in 1.x); it raises ``KeyError`` for
  ``ElasticDocDict``.
* ``ExpirableRedisHashDict`` removes expired keys lazily, when they are read.
  ``len()`` and ``keys()`` can include expired keys that were not read yet; use
  ``iter_fresh_items()`` to skip them. Reading an expired key with ``d[key]``
  raises ``ExpirableRedisHashDict.KeyExpiredError`` (a ``KeyError``).

Transactions with ``RedisPipe``:

.. code:: python

    client = RedisPipe()
    with client:                 # MULTI ... EXEC on exit
        client.set("a", 1)
        client.incr("b")
    client.transaction_results   # [True, 1]

Commands issued in the ``with`` block (in the current thread only) are queued
and executed when the block exits; if the block raises they are discarded.
Blocks can be nested; the outermost one executes the transaction. Reads inside
the block return the pipeline, not values.

``QueueApi`` example:

.. code:: python

    from dict_db.redis_ds.message_queue import JSONMessageQueue, QueueApi

    class Greeter(QueueApi):
        def greet(self, who):
            print("hello", who)

    Greeter(["greeter"]).run()   # blocks; handles {"$name": "greet", "who": "..."}

    # elsewhere
    JSONMessageQueue(["greeter"]).write({"$name": "greet", "who": "world"})

Only public methods defined by the subclass can be called (or exactly the
names in ``EXPOSED_METHODS`` if you set it). A message that fails is logged
and does not stop ``run()``.

Elasticsearch (``dict_db.elastic_ds``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``doc_dict.ElasticDocDict(index, doc_type=None, es=None, refresh=False)``
stores each item as a document whose ``_id`` is the key, in the index
``<index>-<doc_type>`` (lowercased). Keys must be ``str``. Dictionary values
are stored as the document (``.`` in top-level field names is escaped as
``_;_``); other values are stored as ``{"__value__": ..., "__type__": ...}``.
The list of keys is kept in a bookkeeping document with the reserved id
``__ElasticDocDict_Keys`` (that key cannot be used), updated with Painless
scripts, so the cluster must allow inline Painless scripts (the default).

``with docs:`` buffers writes into ``_bulk`` requests that are sent when the
block exits.

.. note::

   The Elasticsearch support has not yet been verified against a live
   Elasticsearch 8/9 cluster; the automated tests use a fake client. Run the
   integration tests (see `Development`_) against a disposable cluster before
   relying on it, and please report any problem you find.

Security
--------

* **Never use the** ``Pickle*`` **classes with data you do not fully trust.**
  ``PickleRedisDict``, ``PickleRedisHashDict``, ``ExpirablePickleRedisHashDict``,
  ``PickleRedisList``, ``PickleRedisSet`` and ``PickleMessageQueue`` call
  ``pickle.loads`` on what they read. Anyone who can write to the Redis keys
  (or publish to the channels) can run arbitrary code in your process. Use the
  ``JSON*`` classes instead.
* Run Redis and Elasticsearch with authentication and TLS, and do not expose
  them to untrusted networks. Pass credentials through the client or the
  ``DICT_DB_*_URL`` environment variables, never in source code.
* ``QueueApi`` executes methods requested by anyone who can publish to its
  channels. Validate handler arguments.
* See `SECURITY.md <SECURITY.md>`_ for how to report a vulnerability.

Migrating from 1.x
------------------

2.0.0 is a major release with breaking changes; see
`CHANGELOG.md <CHANGELOG.md>`_ for the complete list. In short:

* **Python 2 is no longer supported.** Python 3.10+ with redis-py 5+ and
  elasticsearch-py 8+ is required. Keys read from Redis are ``str``.
* **Expirable hash dicts store expiration metadata as plain numbers** instead
  of pickles. Existing Python 2 metadata is still read (parsed without
  unpickling) and a key's metadata is rewritten in the new format the next
  time that key is set or its expiration changes.
* **Elasticsearch**: mapping types are gone, so ``doc_type`` now becomes part of
  the index name (``<index>-<doc_type>``), and the key list is stored as an
  array in a new field. Data written by 1.x (Elasticsearch 2.x) has to be
  reindexed; it cannot be read by Elasticsearch 8/9 anyway.
* ``RedisDict.__getitem__`` / ``RedisPathDict.__getitem__`` raise ``KeyError``
  for missing keys instead of returning ``None`` (``get()`` still returns the
  default, and now also for stored falsy values such as ``0`` or ``""``).
* ``RedisList`` indexing raises ``IndexError`` when out of range, and slices
  follow Python semantics (``lst[:1]`` returns one element, not two).
* ``RedisPathDict.keys()`` returns the logical keys, not the full Redis paths.
* ``QueueApi`` only dispatches to handler methods (see above).
* ``DictDbFactory.create`` raises ``ValueError`` for unknown types instead of
  returning ``None``.
* ``ExpirableRedisHashDict.get()`` honours expiration, and assigning a key
  resets its expiration to the default.

Development
-----------

.. code:: bash

    python -m venv .venv && . .venv/bin/activate
    pip install -e ".[dev]"
    pytest --cov            # uses fakeredis and a fake Elasticsearch client
    ruff check . && ruff format --check .
    mypy

The tests do not need running servers. Optional integration tests run against
live, disposable servers (they create and delete keys and an index named
``dict-db-it-*``) when the matching environment variable is set:

.. code:: bash

    DICT_DB_REDIS_URL=redis://localhost:6379/15 \
    DICT_DB_ELASTIC_URL=http://localhost:9200 pytest -m integration

See `CONTRIBUTING.md <CONTRIBUTING.md>`_.

Next in module Development
--------------------------
- Organizing the interface
- Adding additional DB support
- wrapping queries into __getitem__

Contact me (py@bitweis.com) if you need these anytime soon.
