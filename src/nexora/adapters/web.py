"""Reads one web page the operator points at, so that a claim in a script can be tied to where it was published.

It fetches only the address it is given and never follows a search on its own. The address leaves this machine, so it
counts as a cloud tool and privacy mode refuses it.
"""
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

SKIP = frozenset({"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button"})
BLOCK = frozenset({"p", "li", "h1", "h2", "h3", "h4", "blockquote", "td", "div", "br", "section", "article"})
MAX_BYTES = 2_000_000


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.parts = "", {}, []
        self._skip, self._in_title = 0, False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = dict(attrs)
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def read_html(html: str) -> dict:
    page = _Page()
    page.feed(html)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(page.parts).split("\n")]
    meta = page.meta
    return {"title": (meta.get("og:title") or page.title).strip(), "publisher": meta.get("og:site_name", ""),
            "date": (meta.get("article:published_time") or meta.get("date") or "")[:10],
            "text": "\n".join(line for line in lines if len(line) > 40)}


class WebReader(Adapter):
    def describe(self) -> Capability:
        return Capability(name="web", operations=("read",), runs="cloud")

    def submit(self, request: Request) -> Result:
        url = str(request.inputs["url"]).strip()
        if urlparse(url).scheme not in ("http", "https"):
            raise AdapterError(ErrorCode.INVALID_REQUEST, "only http and https addresses can be read")
        req = urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0 (Macintosh) NEXORA research reader"})
        try:
            with urllib.request.urlopen(req, timeout=request.deadline_seconds or 20) as r:
                kind = r.headers.get_content_type()
                if kind not in ("text/html", "text/plain", "application/xhtml+xml"):
                    raise AdapterError(ErrorCode.INVALID_REQUEST, f"this address holds {kind}, not a page of text")
                raw = r.read(MAX_BYTES).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
        except urllib.error.HTTPError as err:
            raise AdapterError(ErrorCode.INVALID_REQUEST if err.code in (403, 404, 410) else ErrorCode.UNAVAILABLE, f"the page answered {err.code}") from None
        except TimeoutError:
            raise AdapterError(ErrorCode.TIMEOUT, "the page did not answer in time") from None
        except (urllib.error.URLError, ConnectionError) as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"the page is not reachable: {err}") from None
        page = read_html(raw) if kind != "text/plain" else {"title": "", "publisher": "", "date": "", "text": raw}
        return Result(outputs={**page, "publisher": page["publisher"] or urlparse(url).netloc.removeprefix("www."), "url": url})
