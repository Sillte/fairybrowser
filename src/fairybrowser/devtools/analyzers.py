from pathlib import Path

from fairybrowser.devtools.models.http_transaction import HTTPTransaction
from fairybrowser.devtools.models.network_log import NetworkLog


class HTTPTransactionAnalyzer:
    def __init__(self, log_folder: Path | str):
        self.log_folder = Path(log_folder)
        if not self.log_folder.is_dir():
            raise FileNotFoundError(f"HTTP log folder does not exist: {self.log_folder}")

    def get_transactions(self, method: str | None = None, path: str | None = None) -> list[HTTPTransaction]:
        """Acquire HTTP transactions matching the optional method and URL filters."""
        transactions = NetworkLog.load(self.log_folder).http_transactions
        if method:
            transactions = [elem for elem in transactions if method.lower() in elem.request.method.lower()]
        if path:
            transactions = [elem for elem in transactions if path.lower() in elem.request.url.lower()]
        return transactions

    @property
    def transactions(self) -> list[HTTPTransaction]:
        """Acquire all HTTP transactions."""
        return self.get_transactions()
