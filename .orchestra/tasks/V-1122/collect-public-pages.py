"""Read public pages only; retain metadata and directory links, never raw HTML.

No credentials, cookies, model calls, enrollment, or execution of fetched content.
Run from the repository root with the broker-provisioned uv and existing .venv.
"""

import concurrent.futures
import datetime
import hashlib
import html.parser
import json
import urllib.error
import urllib.parse
import urllib.request


URLS = (
    "https://openai.com/business/plugins/sentinelx/",
    "https://chatgpt.com/plugins/plugin_asdk_app_69f63e01766881919640f03b5e7912a5",
    "https://sentinelx.app/",
    "https://sentinelx.app/privacy",
    "https://sentinelx.app/terms",
    "https://sentinelx.app/plans",
    "https://sentinelx.app/troubleshooting",
    "https://developers.openai.com/plugins/quickstart",
    "https://developers.openai.com/api/docs/guides/custom-mcp-server",
    "https://developers.openai.com/plugins/build/auth",
    "https://developers.openai.com/api/docs/guides/secure-mcp-tunnels",
    "https://learn.chatgpt.com/docs/enterprise/work-admin-faq",
    "https://learn.chatgpt.com/docs/pricing",
    "https://learn.chatgpt.com/docs/models",
    "https://learn.chatgpt.com/docs/sign-in-with-chatgpt",
    "https://help.openai.com/en/articles/20001354-gpt-6-and-other-models-in-chatgpt",
    "https://opencode.ai/docs/providers",
    "https://opencode.ai/docs/en/mcp-servers",
    "https://aiget.tech/en/terms",
    "https://sentinelx.ai/",
    "https://chromewebstore.google.com/detail/sentinel-x/cjoolacicinabmgfnbnllhagabgbeghc",
)


class Metadata(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title_parts = []
        self.directory_links = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "a":
            href = attrs.get("href", "")
            host = urllib.parse.urlsplit(href).hostname
            if host == "chatgpt.com" and "sentinelx" in href.lower():
                self.directory_links.add(href)
            if host == "chatgpt.com" and "69f63e01766881919640f03b5e7912a5" in href:
                self.directory_links.add(href)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)


def fetch(url):
    record = {"url": url, "retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat()}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "V-1122-public-research/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(8 * 1024 * 1024 + 1)
            record.update(status=response.status, final_url=response.url)
        if len(body) > 8 * 1024 * 1024:
            return {**record, "error": "response_too_large"}
        parser = Metadata()
        parser.feed(body.decode("utf-8", errors="replace"))
        record.update(
            bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            title=" ".join("".join(parser.title_parts).split())[:180],
            directory_links=sorted(parser.directory_links),
        )
    except urllib.error.HTTPError as exc:
        record.update(error="HTTPError", status=exc.code)
    except Exception as exc:
        record.update(error=type(exc).__name__)
    return record


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        records = list(executor.map(fetch, URLS))
    print(json.dumps(records, ensure_ascii=False, indent=2))
