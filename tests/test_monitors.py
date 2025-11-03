import os
from fairybrowser.monitors import is_pid_alive


def test_is_pid_alive_current():
    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_fake():
    # 大きな PID は存在しないはず
    assert is_pid_alive(999999) is False
