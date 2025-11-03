from fairybrowser.devtools.models import RawCommunicationInfo

def test_model_validate_handles_none_base64():
    data = {
        "url": "https://example.com",
        "method": "GET",
        "request_body": None,
        "response_body": None
    }

    instance = RawCommunicationInfo.model_validate(data)
    assert instance.request_body is None
    assert instance.response_body is None


def test_round_trip_dump_then_validate():
    original = RawCommunicationInfo(
        status=200,
        url="https://example.com",
        method="POST",
        request_body=b'hello world',
        response_body=b'{"ok": true}'
    )

    dumped = original.model_dump()
    restored = RawCommunicationInfo.model_validate(dumped)

    # 完全に復元されるか
    assert restored.status == original.status
    assert restored.url == original.url
    assert restored.method == original.method
    assert restored.request_body == original.request_body
    assert restored.response_body == original.response_body
    assert restored.request_headers == original.request_headers
    assert restored.response_headers == original.response_headers
    assert restored.timing == original.timing



