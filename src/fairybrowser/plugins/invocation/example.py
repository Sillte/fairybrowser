from fairybrowser.invocation import InvocationCreator


class ExampleInvocationPlugin:
    name = "example"

    def create(self):
        return InvocationCreator.from_any(
            on_start=lambda _input, _page, context: context.complete(),
            on_completed=lambda _page, _context: "Example invocation completed",
        )
