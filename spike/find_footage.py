"""Spike helper: list freely licensed videos on Wikimedia Commons for a query (stdlib only)."""
import json, sys, urllib.parse, urllib.request

def search(q, lo=45, hi=420, max_mb=400):
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"filetype:video {q}",
              "gsrnamespace": 6, "gsrlimit": 20, "prop": "videoinfo", "viprop": "url|size|mime|extmetadata|derivatives"}
    req = urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "NEXORA-spike/0.1 (personal test)"})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    out = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        vi = (page.get("videoinfo") or [{}])[0]
        dur, mb = vi.get("duration", 0), vi.get("size", 0) / 1e6
        if lo <= dur <= hi and mb <= max_mb:
            em = vi.get("extmetadata", {})
            out.append({"title": page["title"], "duration": dur, "mb": round(mb, 1), "w": vi.get("width"), "h": vi.get("height"),
                        "license": em.get("LicenseShortName", {}).get("value", "?"), "url": vi.get("url"),
                        "page": vi.get("descriptionurl"), "derivatives": vi.get("derivatives", [])})
    return out

if __name__ == "__main__":
    for q in sys.argv[1:]:
        print("==", q)
        for v in search(q):
            print(f"{v['duration']:6.0f}s {v['mb']:6.1f}MB {v['w']}x{v['h']} {v['license'][:12]:12s} {v['title'][:90]}")
