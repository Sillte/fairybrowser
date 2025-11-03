from playwright.sync_api import Page, BrowserContext, Frame
from pathlib import Path
from typing import Any
from pydantic import BaseModel, JsonValue
import logging
import hashlib
import json 
import base64
import datetime
import shutil
import time
import re

from fairybrowser.devtools.models import RawCommunicationInfo, RawConsoleInfoElem, RawConsoleInfo
from fairybrowser.devtools.collectors import DevtoolsUser


if __name__ == "__main__":
    from fairybrowser import  sync_page
    with sync_page() as page:
        DevtoolsUser(page).start()
        page.goto("about:blank")
        test_url = "https://httpbin.org/post"
        payload = {"foo": "bar", "num": 123}
        page.evaluate(f'''
            fetch("{test_url}", {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({json.dumps(payload)})
            }});
        ''')
        page.wait_for_timeout(5000)
