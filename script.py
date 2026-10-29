import logging

from fairybrowser.invocation import (
    HTTPTransactionListener,
    InvocationCreator,
    InvocationExecutor,
)

logger = logging.getLogger(__name__)


def start(url, page, context):
    page.goto(url)


def collect_api_call(transaction, context):
    if "/api/" in transaction.request.url:
        context.state.setdefault("api_calls", []).append(
            {
                "method": transaction.request.method,
                "url": transaction.request.url,
                "status": transaction.response.status if transaction.response else None,
            }
        )

    context.complete()


if __name__ == "__main__":
    creator = InvocationCreator.from_any(
        on_start=start,
        on_completed=lambda context: context.state.get("api_calls", []),
        listeners=HTTPTransactionListener.from_any(collect_api_call),
    )

    api_calls = InvocationExecutor.from_any(creator).invoke("https://example.com")
    logger.info("API calls: %s", api_calls)
