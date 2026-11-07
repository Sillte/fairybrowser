from fairybrowser.plugins.readers import PageReaderCreator


class ExamplePageReaderPlugin:
    name = "example"

    def create(self):
        return PageReaderCreator.from_any(read=lambda page: page.title())
