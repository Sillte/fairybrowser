from fairybrowser.plugins import PageReaderPlugin
from fairybrowser.plugins.readers import PageReaderCreator


class ExamplePageReaderPlugin(PageReaderPlugin):
    name = "example"

    def create(self):
        return PageReaderCreator.from_any(read=lambda page: page.title())
