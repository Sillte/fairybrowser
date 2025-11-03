import json
from pathlib import Path
from fairybrowser.devtools.analyzers import SimpleRequestAnalyzer
from fairybrowser.devtools.models import RawCommunicationInfo


def _write_raw_list(path: Path, raw_list: list[RawCommunicationInfo]):
    data = [elem.model_dump() for elem in raw_list]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def test_simple_request_analyzer_basic(tmp_path: Path):
    out = tmp_path / "debug"
    out.mkdir()

    raw = RawCommunicationInfo(
        status=200,
        url="https://example.com/api/resource",
        method="POST",
        timing={"requestTime": "1.23"},
        request_headers={"Content-Type": "application/json"},
        response_headers={"Content-Type": "application/json"},
        request_body=b"{\"foo\": \"bar\", \"num\": 123}",
        response_body=b"{\"result\": \"ok\"}",
    )

    file_path = out / "req1.json"
    _write_raw_list(file_path, [raw])

    analyzer = SimpleRequestAnalyzer(out)
    simples = analyzer.get_simple_requests()
    assert len(simples) == 1
    s = simples[0]
    assert s.method.upper() == "POST"
    assert "example.com/api/resource" in s.url
    assert s.status == 200
    # parsed payload and response
    assert isinstance(s.payload, dict)
    assert s.payload.get("foo") == "bar"
    assert isinstance(s.response_json, dict)
    assert s.response_json.get("result") == "ok"


def test_simple_request_analyzer_filters(tmp_path: Path):
    out = tmp_path / "debug2"
    out.mkdir()

    r1 = RawCommunicationInfo(status=200, url="https://site/a", method="GET", request_headers={}, response_headers={}, request_body=b"", response_body=b"")
    r2 = RawCommunicationInfo(status=201, url="https://site/b/path", method="POST", request_headers={}, response_headers={}, request_body=b"{}", response_body=b"{}")
    _write_raw_list(out / "a.json", [r1])
    _write_raw_list(out / "b.json", [r2])

    analyzer = SimpleRequestAnalyzer(out)
    allr = analyzer.get_simple_requests()
    assert len(allr) == 2

    posts = analyzer.get_simple_requests(method="post")
    assert len(posts) == 1
    assert posts[0].method.upper() == "POST"

    path_filtered = analyzer.get_simple_requests(path="/b/")
    assert len(path_filtered) == 1
    assert "/b/" in path_filtered[0].url
