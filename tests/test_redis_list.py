import pytest

from dict_db.redis_ds.redis_list import JSONRedisList, PickleRedisList, RedisList


@pytest.mark.parametrize("cls", [RedisList, PickleRedisList, JSONRedisList])
def test_append_index_pop(cls, client):
    rl = cls("l", redis_client=client)
    assert len(rl) == 0
    rl.append("a")
    rl.append("b")
    assert len(rl) == 2
    assert rl[0] == "a"
    assert rl[-1] == "b"
    assert rl[:] == ["a", "b"]
    assert rl.pop() == "b"
    assert rl.pop() == "a"
    assert rl.pop() is None


@pytest.fixture
def numbers(client):
    rl = JSONRedisList("n", redis_client=client)
    for i in range(6):
        rl.append(i)
    return rl


@pytest.mark.parametrize(
    "sl",
    [
        slice(None),
        slice(0, 1),
        slice(None, 3),
        slice(2, None),
        slice(-2, None),
        slice(None, -1),
        slice(0, 0),
        slice(4, 2),
        slice(None, None, 2),
        slice(None, None, -1),
        slice(1, 100),
    ],
)
def test_slices_follow_python_semantics(numbers, sl):
    assert numbers[sl] == list(range(6))[sl]


def test_index_out_of_range(numbers):
    with pytest.raises(IndexError):
        numbers[6]
    with pytest.raises(IndexError):
        numbers[-7]
    with pytest.raises(TypeError):
        numbers["0"]


def test_iteration_and_repr(numbers):
    assert list(numbers) == list(range(6))
    assert repr(numbers) == "RedisList([0, 1, 2, 3, 4, 5])"


def test_setitem(numbers):
    numbers[0] = "x"
    assert numbers[0] == "x"
    with pytest.raises(IndexError):
        numbers[10] = "y"


def test_head_operations(client):
    rl = JSONRedisList("l", redis_client=client)
    rl.append(1)
    rl.append(0, head=True)
    assert list(rl) == [0, 1]
    assert rl.pop(head=True) == 0


def test_blocking_pop(client):
    rl = JSONRedisList("l", redis_client=client)
    rl.append({"x": 1})
    rl.append({"y": 2})
    assert rl.pop(blocking=True, timeout=1) == {"y": 2}
    assert rl.pop(head=True, blocking=True, timeout=1) == {"x": 1}
    assert rl.pop(blocking=True, timeout=0.1) is None


def test_trim_and_delete(numbers, client):
    numbers.trim(1, 2)
    assert list(numbers) == [1, 2]
    numbers.delete()
    assert not client.exists("n")
    assert numbers.client is client
