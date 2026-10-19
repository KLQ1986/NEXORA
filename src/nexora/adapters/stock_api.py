"""Pexels and Pixabay asked directly, in the language of the words (design 2026-10-19, section 1).

OpenMontage reaches these two libraries too, but always in English: their APIs take the language of a search (`locale` for
Pexels, `lang` for Pixabay), and a line about a floating market finds more in Vietnamese on a library with Vietnamese
uploads. Each answer is a candidate in the shape every NEXORA stock source gives, with a small file to watch it from its
source and the largest to fetch when it is chosen. Only the words and the key leave the machine; nothing is downloaded here
until a candidate is chosen.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from nexora.adapters.web import public_address
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

AGENT = "NEXORA/1.0 (personal video tool)"
PEXELS = "https://api.pexels.com/videos/search"
PIXABAY = "https://pixabay.com/api/videos/"
LOCALES = {"vi": "vi-VN", "en": "en-US"}


def fetch_public(url: str, path: str | Path, *, max_bytes: int = 2_000_000_000, timeout: float = 60.0, headers: dict | None = None) -> Path:
    """Save one file from the public web, refusing an address on this machine or the local network and anything larger
    than `max_bytes`."""
    public_address(url)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as answer, open(partial, "wb") as out:
            written = 0
            while chunk := answer.read(1 << 16):
                written += len(chunk)
                if written > max_bytes:
                    raise AdapterError(ErrorCode.INVALID_REQUEST, f"the file is larger than {max_bytes} bytes")
                out.write(chunk)
    except AdapterError:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, ValueError) as err:
        partial.unlink(missing_ok=True)
        raise AdapterError(ErrorCode.UNAVAILABLE, f"could not fetch {urllib.parse.urlparse(url).hostname}: {err}") from None
    partial.replace(path)
    return path


def _get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as answer:
            return json.loads(answer.read().decode("utf-8"))
    except (OSError, ValueError) as err:
        raise AdapterError(ErrorCode.UNAVAILABLE, f"{urllib.parse.urlparse(url).hostname}: {err}") from None


def pexels_candidate(v: dict, query: str) -> dict:
    files = [f for f in v.get("video_files") or [] if f.get("link") and (f.get("file_type") or "video/mp4") == "video/mp4"]
    by_width = sorted(files, key=lambda f: f.get("width") or 0)
    small = next((f for f in by_width if (f.get("width") or 0) >= 480), by_width[0] if by_width else {})
    large = next((f for f in reversed(by_width) if (f.get("width") or 0) <= 3840), by_width[-1] if by_width else {})
    return {"source": "pexels", "source_id": str(v.get("id")), "source_url": v.get("url", ""), "download_url": large.get("link", ""),
            "preview_url": small.get("link", ""), "thumbnail_url": v.get("image", ""), "width": int(large.get("width") or v.get("width") or 0),
            "height": int(large.get("height") or v.get("height") or 0), "duration": float(v.get("duration") or 0), "creator": (v.get("user") or {}).get("name", ""),
            "license": "Pexels License", "tags": "", "query": query}


def pixabay_candidate(h: dict, query: str) -> dict:
    sizes = h.get("videos") or {}
    large = next((sizes[k] for k in ("large", "medium", "small", "tiny") if (sizes.get(k) or {}).get("url")), {})
    small = next((sizes[k] for k in ("tiny", "small", "medium") if (sizes.get(k) or {}).get("url")), {})
    thumb = next(((sizes.get(k) or {}).get("thumbnail") for k in ("medium", "small", "large", "tiny") if (sizes.get(k) or {}).get("thumbnail")), "")
    return {"source": "pixabay", "source_id": str(h.get("id")), "source_url": h.get("pageURL", ""), "download_url": large.get("url", ""),
            "preview_url": small.get("url", ""), "thumbnail_url": thumb, "width": int(large.get("width") or 0), "height": int(large.get("height") or 0),
            "duration": float(h.get("duration") or 0), "creator": h.get("user", ""), "license": "Pixabay Content License", "tags": h.get("tags", ""), "query": query}


class StockApi(Adapter):
    """Pexels and Pixabay with their keys; a library without a key is simply not asked."""

    def __init__(self, *, pexels_key: str = "", pixabay_key: str = ""):
        self._pexels, self._pixabay = pexels_key, pixabay_key

    def sources(self) -> list[str]:
        return [name for name, key in (("pexels", self._pexels), ("pixabay", self._pixabay)) if key]

    def describe(self) -> Capability:
        return Capability(name="stock_api", operations=("candidates", "download"), runs="cloud")

    def environment(self) -> dict:
        return {"sources": self.sources()}

    def submit(self, request: Request) -> Result:
        if not self.sources():
            raise AdapterError(ErrorCode.UNAVAILABLE, "no Pexels or Pixabay key is set", retryable=False)
        if request.operation == "download":
            c = request.inputs["candidate"]
            ext = Path(c["download_url"].split("?")[0]).suffix.lower() or ".mp4"
            path = fetch_public(c["download_url"], Path(request.params["out_dir"]) / f"{c['source']}_{c['source_id']}{ext}")
            return Result(outputs={"path": str(path)}, files=(str(path),))
        lang = request.params.get("lang", "en")
        per = max(3, min(40, int(request.params.get("per_query", 8))))
        wanted = request.params.get("sources") or self.sources()
        found, errors = [], {}
        for query in request.inputs["queries"]:
            if self._pexels and "pexels" in wanted:
                try:
                    url = PEXELS + "?" + urllib.parse.urlencode({"query": query, "per_page": per, "locale": LOCALES.get(lang, "en-US"), "size": "medium"})
                    found += [pexels_candidate(v, query) for v in _get_json(url, {"Authorization": self._pexels}).get("videos", [])]
                except AdapterError as err:
                    errors["pexels"] = err.message
            if self._pixabay and "pixabay" in wanted:
                try:
                    url = PIXABAY + "?" + urllib.parse.urlencode({"key": self._pixabay, "q": query[:100], "per_page": per, "lang": lang, "safesearch": "true"})
                    found += [pixabay_candidate(h, query) for h in _get_json(url).get("hits", [])]
                except AdapterError as err:
                    errors["pixabay"] = err.message
        return Result(outputs={"candidates": [c for c in found if c["download_url"]], "errors": errors})
