"""ポートユーティリティ

提供関数:
- is_port_free(port, host='127.0.0.1') -> bool
- find_available_port(preferred: Optional[Iterable[int]] = None, host='127.0.0.1', start=1024, end=65535) -> int

説明:
preferred を受け取った場合はそのリストを先に試し、利用可能なら返します。
見つからなければ start..end の範囲を順にスキャンして最初に見つかった利用可能なポートを返します。
それでも見つからなければ OS に割り当てを依頼して空いているエフェメラルポートを返します。

注意点:
- この関数はローカルでのバインド可否で判断します。瞬間的な競合により、呼び出し後に別プロセスがポートを取得する可能性は残ります。
"""

from typing import Iterable, Optional
import socket


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """指定した (host, port) にバインドできるか試し、可能なら True を返す。

    ポートが既に使用中の場合は False を返す。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # 再利用オプションをセットして素早く判定
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def can_connect_port(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True  # 接続成功
        except (ConnectionRefusedError, socket.timeout):
            return False
    return False


def find_available_port(
    preferred: Optional[Iterable[int]] = None,
    *,
    host: str = "127.0.0.1",
    start: int = 1024,
    end: int = 65535,
) -> int:
    """利用可能なポートを返す。

    - preferred が与えられれば先にその順で試す。
    - 見つからなければ start..end を順にスキャンする。
    - それでも見つからなければ OS に ephemeral port を割り当ててもらって返す。

    戻り値: 利用可能なポート番号（int）。
    例外: 範囲外の値やマイナスは受け付けない。
    """
    if preferred:
        for p in preferred:
            if not (0 <= p <= 65535):
                continue
            if is_port_free(p, host):
                return p

    # 範囲チェック
    if start < 0:
        start = 0
    if end > 65535:
        end = 65535

    for port in range(start, end + 1):
        if is_port_free(port, host):
            return port

    # 最後の手段: OS に ephemeral port を割り当ててもらう
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]
