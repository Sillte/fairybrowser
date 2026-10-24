import json
from pathlib import Path

from fairybrowser.devtools.analyzers import HTTPTransactionAnalyzer
from fairybrowser.devtools.models.http_transaction import HTTPRequest, HTTPResponse, HTTPTransaction


def _write_transaction_list(path: Path, transactions: list[HTTPTransaction]):
    data = [transaction.model_dump(mode="json") for transaction in transactions]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def test_http_transaction_analyzer_basic(tmp_path: Path):
    out = tmp_path / "debug"
    out.mkdir()

    transaction = HTTPTransaction(
        request=HTTPRequest(
            url="https://example.com/api/resource",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=b'{"foo": "bar", "num": 123}',
        ),
        response=HTTPResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b'{"result": "ok"}',
        ),
        time=1.23,
    )

    file_path = out / "req1.json"
    _write_transaction_list(file_path, [transaction])

    analyzer = HTTPTransactionAnalyzer(out)
    transactions = analyzer.get_transactions()
    assert len(transactions) == 1
    transaction = transactions[0]
    assert transaction.request.method == "POST"
    assert "example.com/api/resource" in transaction.request.url
    assert transaction.response is not None
    assert transaction.response.status == 200
    assert isinstance(transaction.request.body_json, dict)
    assert transaction.request.body_json["foo"] == "bar"
    assert isinstance(transaction.response.body_json, dict)
    assert transaction.response.body_json["result"] == "ok"
    assert transaction.time == 1.23


def test_http_transaction_analyzer_filters(tmp_path: Path):
    out = tmp_path / "debug2"
    out.mkdir()

    r1 = HTTPTransaction(
        request=HTTPRequest(url="https://site/a", method="GET"),
        response=HTTPResponse(status=200),
    )
    r2 = HTTPTransaction(
        request=HTTPRequest(url="https://site/b/path", method="POST", body=b"{}"),
        response=HTTPResponse(status=201, body=b"{}"),
    )
    _write_transaction_list(out / "a.json", [r1])
    _write_transaction_list(out / "b.json", [r2])

    analyzer = HTTPTransactionAnalyzer(out)
    transactions = analyzer.get_transactions()
    assert len(transactions) == 2

    posts = analyzer.get_transactions(method="post")
    assert len(posts) == 1
    assert posts[0].request.method == "POST"

    path_filtered = analyzer.get_transactions(path="/b/")
    assert len(path_filtered) == 1
    assert "/b/" in path_filtered[0].request.url


def test_http_transaction_without_response(tmp_path: Path):
    out = tmp_path / "debug3"
    out.mkdir()
    _write_transaction_list(
        out / "req.json",
        [HTTPTransaction(request=HTTPRequest(url="https://example.com", method="GET"))],
    )

    transaction = HTTPTransactionAnalyzer(out).get_transactions()[0]
    assert isinstance(transaction, HTTPTransaction)
    assert transaction.response is None
