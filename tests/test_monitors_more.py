import os
import json
import socket
from fairybrowser.models import ExecutionState, BrowserInfo
from fairybrowser import monitors
from unittest.mock import patch, MagicMock
from contextlib import contextmanager


def _state_path(name: str):
    return monitors._states_folder / f"{name}.json"


def teardown_state(name: str):
    p = _state_path(name)
    if p.exists():
        p.unlink()

@contextmanager
def mock_browser_alive(alive_ports: list[int]):
    """
    Simulate the monitor's 
    """
    target = "fairybrowser.monitors.urllib.request.urlopen"
    
    def side_effect(url, timeout=None):
        # url は文字列（http://127.0.0.1:13456/json/version）として渡されるので
        # ポート番号を抽出する
        import re
        match = re.search(r":(\d+)/", url if isinstance(url, str) else url.geturl())
        port = int(match.group(1)) if match else None

        if port in alive_ports:
            # 成功時のレスポンスを生成
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = json.dumps({"Browser": "Mocked/1.0"}).encode()
            mock_response.__enter__.return_value = mock_response
            return mock_response
        else:
            # 失敗時は例外を投げる
            raise urllib.error.URLError(f"Connection refused for port {port}")

    with patch(target) as mock_url_open:
        mock_url_open.side_effect = side_effect
        yield mock_url_open


def test_save_load_and_get_pid():
    name = "test_fairy_save"
    info = BrowserInfo(name=name)
    state = ExecutionState(name=name, type=info.type, port=0, pid=os.getpid())
    try:
        monitors.save_state(state)
        loaded = monitors.load_state(info)
        assert loaded.name == state.name
        assert loaded.type == state.type
        assert loaded.pid == state.pid
    finally:
        teardown_state(name)


def test_is_existent_true_when_pid_alive_and_port_bound():
    name = "test_fairy_exist"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        info = BrowserInfo(name=name, type="chromium")
        state = ExecutionState(name=info.name, type=info.type, port=port, pid=os.getpid())
        monitors.save_state(state)
        with mock_browser_alive([port]):
            assert monitors.is_existent(info) is True
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
        alive = ExecutionState(
            name=alive_name, type="chromium", port=port, pid=os.getpid()
        )
        monitors.save_state(alive)

        dead = ExecutionState(name=dead_name, type="chromium", port=0, pid=999999)
        monitors.save_state(dead)

        with mock_browser_alive([port]):
            infos = monitors.get_execution_infos()
        alive_names = {info.name for info in infos}
        assert alive_name in alive_names
        assert dead_name not in alive_name
    finally:
        s.close()
        teardown_state(alive_name)
        teardown_state(dead_name)
