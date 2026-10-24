import json
from itertools import chain
from pathlib import Path

from fairybrowser.devtools.models.http_transaction import RawCommunicationInfo
from fairybrowser.devtools.models.http_transaction import HTTPTransaction


class HTTPTransactionAnalyzer:
    def __init__(self, log_folder: Path | str):
        self.log_folder = Path(log_folder)
        assert self.log_folder.exists()

    def get_transactions(self, method: str | None = None, path: str | None = None) -> list[HTTPTransaction]:
        """Acquire HTTP transactions matching the optional method and URL filters."""
        raw_infos = self.raw_infos
        transactions = [HTTPTransaction.from_raw(elem) for elem in raw_infos]
        if method:
            transactions = [elem for elem in transactions if method.lower() in elem.request.method.lower()]
        if path:
            transactions = [elem for elem in transactions if path.lower() in elem.request.url.lower()]
        return transactions

    @property
    def transactions(self) -> list[HTTPTransaction]:
        """Acquire all HTTP transactions."""
        return self.get_transactions()

    @property
    def raw_infos(self) -> list[RawCommunicationInfo]:
        result = []
        for path in self._paths_iterable:
            data = json.loads(path.read_text())
            result += [RawCommunicationInfo.model_validate(elem) for elem in data]
        return result

    @property
    def _paths_iterable(self):
        return chain(self.log_folder.glob("*.json"), self.log_folder.glob("./network/*.json"))
