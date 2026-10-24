from fairybrowser.invocation.exceptions import InvocationException


def test_invocation_exception_exposes_original_exception_and_traceback():
    try:
        raise ValueError("invalid value")
    except ValueError as original:
        original_exception = original
        original_traceback = original.__traceback__
        wrapped = InvocationException(original)

    assert wrapped.exception_type == "ValueError"
    assert wrapped.message == "invalid value"
    assert str(wrapped) == "ValueError: invalid value"
    assert wrapped.original_exception is original_exception
    assert wrapped.original_traceback is original_traceback
