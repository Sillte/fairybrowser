import socket
from fairybrowser.port_utils import find_available_port, is_port_free


def test_is_port_free_and_bound_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        assert is_port_free(port) is False
    finally:
        s.close()
    # after close it should be free (usually)
    assert is_port_free(port) is True


def test_find_available_port_prefers_given():
    # allocate an ephemeral port and then close it so it becomes available
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    candidate = s.getsockname()[1]
    s.close()

    p = find_available_port(preferred=[candidate])
    assert p == candidate


def test_find_available_port_range():
    # ask for a small range; should return a port within it
    port = find_available_port(start=15000, end=15010)
    assert 15000 <= port <= 15010
