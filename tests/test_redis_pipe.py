import threading

import pytest

from dict_db.redis_ds.redis_pipe import RedisPipe


def test_commands_outside_transaction_run_immediately(client):
    client.set("a", 1)
    assert client.get("a") == b"1"
    assert not client.in_transaction


def test_transaction_executes_on_exit_and_stores_results(client):
    with client as c:
        assert c is client
        assert client.in_transaction
        client.set("a", 1)
        client.incr("a")
        # Nothing is executed yet.
        assert client.connection_pool is not None
    assert not client.in_transaction
    assert client.get("a") == b"2"
    assert client.transaction_results == [True, 2]


def test_transaction_is_discarded_on_exception(client):
    with pytest.raises(RuntimeError), client:
        client.set("a", 1)
        raise RuntimeError("boom")
    assert client.get("a") is None
    assert not client.in_transaction
    # The client is usable again afterwards.
    with client:
        client.set("b", 2)
    assert client.get("b") == b"2"


def test_nested_transactions_execute_once_at_outermost_exit(client):
    with client:
        client.set("a", 1)
        with client:
            client.set("b", 2)
        assert client.get("a") is not None  # still queued (returns the pipeline)
        assert client.in_transaction
    assert client.get("a") == b"1"
    assert client.get("b") == b"2"


def test_transaction_does_not_capture_other_threads(client):
    seen = {}

    def other_thread():
        seen["in_tx"] = client.in_transaction
        client.set("other", "x")
        seen["value"] = client.get("other")

    with client:
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()
        client.set("mine", "y")
    assert seen == {"in_tx": False, "value": b"x"}
    assert client.get("mine") == b"y"


def test_constructor_passes_configuration_to_redis():
    pipe = RedisPipe(host="redis.invalid", port=6390, db=3, password="pw")  # noqa: S106
    kwargs = pipe.connection_pool.connection_kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["db"], kwargs["password"]) == (
        "redis.invalid",
        6390,
        3,
        "pw",
    )


def test_from_url_returns_a_redis_pipe():
    pipe = RedisPipe.from_url("redis://redis.invalid:6390/2")
    assert isinstance(pipe, RedisPipe)
    assert pipe.connection_pool.connection_kwargs["db"] == 2
