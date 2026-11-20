import logging
import threading

import pytest

from dict_db.redis_ds.message_queue import (
    JSONMessageQueue,
    MessageQueue,
    PickleMessageQueue,
    QueueApi,
)


@pytest.mark.parametrize("channels", ["chan", None, [1]])
def test_channels_must_be_a_list_of_names(client, channels):
    with pytest.raises(TypeError):
        MessageQueue(channels, redis_client=client)


def test_read_requires_context(client):
    queue = JSONMessageQueue(["c"], redis_client=client)
    with pytest.raises(RuntimeError):
        queue.read()


@pytest.mark.parametrize("cls", [MessageQueue, JSONMessageQueue, PickleMessageQueue])
def test_write_then_read(cls, client):
    reader = cls(["c"], redis_client=client)
    writer = cls(["c"], redis_client=client)
    message = "hello" if cls is MessageQueue else {"n": [1, 2]}
    with reader:
        writer.write(message, timeout=1)
        assert reader.read(timeout=1) == message
        assert reader.read(block=False) is None
        assert reader.read(timeout=0.05) is None
    assert reader.channels == ["c"]
    reader.close()


def test_messages_are_received_in_order(client):
    reader = JSONMessageQueue(["c"], redis_client=client)
    writer = JSONMessageQueue(["c"], redis_client=client)
    sent = list(range(20))
    with reader:
        for value in sent:
            writer.write(value, timeout=1)
        assert [reader.read(timeout=1) for _ in sent] == sent


def test_write_without_readers(client):
    writer = JSONMessageQueue(["nobody"], redis_client=client)
    writer.write("dropped", wait_for_readers=False)
    with pytest.raises(TimeoutError):
        writer.write("x", timeout=0.05)


def test_write_waits_for_a_reader(client):
    writer = JSONMessageQueue(["c"], redis_client=client)
    reader = JSONMessageQueue(["c"], redis_client=client)
    received = []

    def read_one():
        with reader:
            received.append(reader.read(timeout=5))

    thread = threading.Thread(target=read_one)
    thread.start()
    writer.write("late", timeout=5)
    thread.join(5)
    assert received == ["late"]


class Greeter(QueueApi):
    def __init__(self, channels, redis_client=None):
        super().__init__(channels, redis_client=redis_client)
        self.calls = []

    def greet(self, who):
        self.calls.append(who)
        return f"hi {who}"

    def _private(self):  # pragma: no cover - must never be called
        raise AssertionError("private method called")


def test_dispatches_to_handler(client):
    api = Greeter(["api"], redis_client=client)
    assert api.message_to_call({"$name": "greet", "who": "bob"}) == "hi bob"
    assert api.calls == ["bob"]


@pytest.mark.parametrize(
    "name",
    [
        "run",
        "write",
        "read",
        "message_to_call",
        "is_exposed",
        "_private",
        "__init__",
        "__class__",
        "calls",
        "nope",
    ],
)
def test_refuses_non_handler_names(client, name):
    api = Greeter(["api"], redis_client=client)
    assert not api.is_exposed(name)
    with pytest.raises(KeyError):
        api.message_to_call({"$name": name})


@pytest.mark.parametrize("msg", [None, "greet", [], {"who": "x"}])
def test_rejects_malformed_messages(client, msg):
    with pytest.raises(ValueError):
        Greeter(["api"], redis_client=client).message_to_call(msg)


def test_non_string_name_is_refused(client):
    with pytest.raises(KeyError):
        Greeter(["api"], redis_client=client).message_to_call({"$name": 5})


def test_explicit_allowlist(client):
    class Strict(Greeter):
        EXPOSED_METHODS = frozenset({"other"})

        def other(self):
            return "ok"

    api = Strict(["api"], redis_client=client)
    assert api.message_to_call({"$name": "other"}) == "ok"
    with pytest.raises(KeyError):
        api.message_to_call({"$name": "greet", "who": "x"})


def test_run_survives_bad_messages(client, caplog):
    api = Greeter(["api"], redis_client=client)
    sender = JSONMessageQueue(["api"], redis_client=client)

    def send_all():
        sender.write({"$name": "greet"}, timeout=5)  # missing argument -> TypeError
        sender.write({"$name": "run"}, timeout=5)  # not allowed
        sender.write("garbage", timeout=5)  # malformed
        sender.write({"$name": "greet", "who": "alice"}, timeout=5)

    thread = threading.Thread(target=send_all)
    thread.start()
    with caplog.at_level(logging.ERROR):
        api.run(max_messages=4)
    thread.join(5)
    assert api.calls == ["alice"]
    assert len([r for r in caplog.records if "Failed to handle" in r.message]) == 3
