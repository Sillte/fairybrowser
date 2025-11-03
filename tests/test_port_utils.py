import socket
from fairybrowser.port_utils import find_available_port, is_port_free


def test_find_available_port_returns_int():
    p = find_available_port()
    assert isinstance(p, int)
    assert 0 < p <= 65535


def test_is_port_free_for_new_socket():
    # 一時的にバインドしているポートは is_port_free が False を返す
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    used_port = s.getsockname()[1]
    try:
        assert is_port_free(used_port) is False
    finally:
        s.close()
