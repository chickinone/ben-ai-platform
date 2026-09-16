import pytest

from ben_litellm_plugins.streaming import StreamRestorer

MAPPING = {"<PHONE_1>": "0912 345 678"}


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 8, 50])
def test_restores_placeholder_split_across_chunks(chunk_size):
    source = "Gọi số <PHONE_1> ngay nhé"
    restorer = StreamRestorer(MAPPING)
    pieces = [restorer.feed(source[i : i + chunk_size]) for i in range(0, len(source), chunk_size)]
    pieces.append(restorer.flush())

    assert "".join(pieces) == "Gọi số 0912 345 678 ngay nhé"
    assert all("PHONE" not in piece and "<PH" not in piece for piece in pieces)


def test_lone_angle_bracket_is_released_once_it_cannot_be_a_placeholder():
    restorer = StreamRestorer(MAPPING)
    first = restorer.feed("a < b")
    second = restorer.feed(" và còn nhiều chữ nữa")
    assert first + second + restorer.flush() == "a < b và còn nhiều chữ nữa"


def test_flush_returns_incomplete_tail_at_end_of_stream():
    restorer = StreamRestorer(MAPPING)
    assert restorer.feed("abc <PHO") == "abc "
    assert restorer.has_pending
    assert restorer.flush() == "<PHO"
    assert not restorer.has_pending
