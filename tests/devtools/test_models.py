from fairybrowser.devtools.models.http_transaction import HTTPRequest, HTTPResponse, HTTPTransaction


def test_transaction_body_serialization_round_trips_text_and_binary():
    original = HTTPTransaction(
        request=HTTPRequest(
            url="https://example.com",
            method="POST",
            body=b"hello world",
        ),
        response=HTTPResponse(status=200, body=b"\x00\xff"),
        time=1.25,
    )

    restored = HTTPTransaction.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.request.body_text == "hello world"
    assert restored.response is not None
    assert restored.response.body == b"\x00\xff"


def test_empty_transaction_bodies_round_trip():
    original = HTTPTransaction(request=HTTPRequest(url="https://example.com", method="GET"))

    restored = HTTPTransaction.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.request.body == b""
