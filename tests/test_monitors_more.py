import json
import os
import socket
import urllib.error
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from fairybrowser import monitors
from fairybrowser.models import BrowserInfo, ExecutionState
from fairybrowser.storage import StoragePathSolver


@pytest.fixture(autouse=True)
def isolate_execution_states(tmp_path, monkeypatch):
    monkeypatch.setattr(monitors, "_storage_path_solver", StoragePathSolver(data_home=tmp_path))


def _state_path(name: str, type: str = "chrome"):
    return monitors._storage_path_solver.execution_states_directory() / type / f"{name}.json"


def teardown_state(name: str, type: str = "chrome"):
    p = _state_path(name, type)
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
            mock_response.read.return_value = json.dumps(
                {"Browser": "Mocked/1.0", "webSocketDebuggerUrl": f"ws://localhost:{port}/devtools/browser/mock"}
            ).encode()
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


def test_is_alive_uses_pid_and_cdp_endpoint_not_bind_probe(monkeypatch):
    state = ExecutionState(name="alive", type="chrome", port=13456, pid=42)
    monkeypatch.setattr(monitors, "is_pid_alive", lambda _pid: True)
    monkeypatch.setattr(monitors, "_is_browser_fetchable", lambda _port: True)
    monkeypatch.setattr(monitors, "is_port_free", lambda _port: True, raising=False)

    assert monitors._is_alive(state)


def test_browser_fetchable_queries_localhost_and_requires_cdp_fields(monkeypatch):
    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps(
        {"Browser": "Chrome/1", "webSocketDebuggerUrl": "ws://localhost:13456/devtools/browser/mock"}
    ).encode()
    response.__enter__.return_value = response
    requested = []
    monkeypatch.setattr(
        monitors.urllib.request,
        "urlopen",
        lambda url, timeout: requested.append((url, timeout)) or response,
    )

    assert monitors._is_browser_fetchable(13456)
    assert requested == [("http://localhost:13456/json/version", 1.0)]


def test_is_existent_true_when_pid_alive_and_port_bound():
    name = "test_fairy_exist"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        info = BrowserInfo(name=name, type="chrome")
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
        alive = ExecutionState(name=alive_name, type="chrome", port=port, pid=os.getpid())
        monitors.save_state(alive)

        dead = ExecutionState(name=dead_name, type="chrome", port=0, pid=999999)
        monitors.save_state(dead)

        with mock_browser_alive([port]):
            infos = monitors.get_execution_infos()
        alive_names = {info.name for info in infos}
        assert alive_name in alive_names
        assert dead_name not in alive_names
    finally:
        s.close()
        teardown_state(alive_name)
        teardown_state(dead_name)
