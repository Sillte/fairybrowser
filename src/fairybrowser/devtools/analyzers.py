import json
from pathlib import Path 
from pathlib import Path 
from itertools import chain 
from fairybrowser.devtools.models import SimpleRequest, RawCommunicationInfo

class SimpleRequestAnalyzer:
    def __init__(self, log_folder: Path | str):
        self.log_folder = Path(log_folder)
        assert self.log_folder.exists()


    def get_simple_requests(self,
                            method: str | None = None, 
                            path: str | None = None) -> list[SimpleRequest]:
        """Acquire the simple requests based on the search parapmeters.
        """
        raw_infos = self.raw_infos
        simple_requests = [SimpleRequest.from_raw(elem) for elem in raw_infos]
        if method:
            simple_requests = [elem for elem in simple_requests if elem.method.lower().find(method.lower()) != -1]
        if path:
            simple_requests = [elem for elem in simple_requests if elem.url.lower().find(path.lower()) != -1]
        return simple_requests

    @property
    def simple_requests(self) -> list[SimpleRequest]:
        """Acquire all the simple requests.
        """
        return self.get_simple_requests()
        

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
