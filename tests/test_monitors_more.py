import os
import socket
from fairybrowser.models import ExecutionInfo
from fairybrowser import monitors


def _state_path(name: str):
    return monitors._states_folder / f"{name}.json"


def teardown_state(name: str):
    p = _state_path(name)
    if p.exists():
        p.unlink()


def test_save_load_and_get_pid():
    name = "test_fairy_save"
    info = ExecutionInfo(name=name, type="chromium", port=0, pid=os.getpid())
    try:
        monitors.save_state(info)
        loaded = monitors.load_state(name)
        assert loaded.name == info.name
        assert loaded.pid == info.pid
        assert monitors.get_pid(name) == info.pid
    finally:
        teardown_state(name)


def test_is_existent_true_when_pid_alive_and_port_bound():
    name = "test_fairy_exist"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        info = ExecutionInfo(name=name, type="chromium", port=port, pid=os.getpid())
        monitors.save_state(info)
        assert monitors.is_existent(name) is True
    finally:
        teardown_state(name)
        s.close()


def test_get_execution_infos_filters():
    # Create one existent and one non-existent entry
    alive_name = "alive_fairy"
    dead_name = "dead_fairy"

    # Bind a port for the alive one
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        alive = ExecutionInfo(name=alive_name, type="chromium", port=port, pid=os.getpid())
        monitors.save_state(alive)

        dead = ExecutionInfo(name=dead_name, type="chromium", port=0, pid=999999)
        monitors.save_state(dead)

        infos = monitors.get_execution_infos()
        assert alive_name in infos
        assert dead_name not in infos
    finally:
        s.close()
        teardown_state(alive_name)
        teardown_state(dead_name)