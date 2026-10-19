"""Stock judged on its previews before anything is downloaded (design 2026-10-19).

For a line that the footage does not show, the scout asks the stock libraries for candidates in the words that fit each of
them (Vietnamese where a library takes it, English everywhere, place names as written), keeps only their small preview
pictures, and judges those: SigLIP for every candidate, then the vision model for the first few. Nothing is downloaded
until a candidate is chosen, by the operator or, when they allow it, as the best one that passes. The candidates of a
project are kept in `stock_candidates` until its storyboard is approved; their previews live in `<tmp>/<project_id>/`.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

from nexora.core import db
from nexora.core.adapter import AdapterError, ErrorCode, PrivacyClass, Request

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_candidates (cid TEXT PRIMARY KEY, project_id TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
  rank REAL NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS stock_candidates_key ON stock_candidates (project_id, key, rank)
"""
KEYWORDS_PROMPT = (
    "Câu lời dẫn của một video: \"{line}\".\nCần tìm video stock minh hoạ câu này. Viết từ khoá tìm kiếm:\n"
    "en: 2 đến 3 cụm tiếng Anh, mỗi cụm 2 đến 5 từ, cụm đầu cụ thể nhất (điều chính câu nói), cụm sau chung hơn;\n"
    "vi: 1 đến 2 cụm tiếng Việt có dấu, ngắn;\n"
    "names: tên riêng địa danh hoặc sự vật trong câu, giữ nguyên chữ viết (có thể rỗng).\n"
    "Chỉ trả về JSON với các khoá en, vi, names (mỗi khoá là một danh sách chuỗi)."
)
JUDGE_PROMPT = (
    "Đây là ảnh xem trước của một video stock. Câu lời dẫn cần minh hoạ: \"{line}\".\n"
    "Trước hết nói điều chiếm nhiều chỗ nhất trong ảnh (chu_the_chinh). Rồi chấm phu_hop từ 0 đến 10 theo thang:\n"
    "10: điều câu nói là chủ thể chính, thấy rõ, đủ mọi chi tiết câu nêu.\n"
    "8: thấy rõ và đúng, nhưng không phải chủ thể chính.\n"
    "6: có thấy nhưng nhỏ, ở xa, bị che, hoặc thiếu một chi tiết câu nêu.\n"
    "4: đúng bối cảnh nhưng không thấy điều chính câu nói.\n"
    "0 đến 2: không liên quan (tin tức, chữ, người không liên quan, nơi khác hẳn).\n"
    "Chỉ trả về JSON với các khoá chu_the_chinh, phu_hop (số), ly_do (một câu ngắn)."
)
LOOK_PASS = 5          # as the Director's look: a candidate that passes shows the line
KEPT = 12              # candidates kept for a line
LOOKED = 3             # of them, the ones the vision model looks at
ROUNDS = 3             # searches for a line: its most precise words first, then broader ones while nothing passes
PER_QUERY = 8          # candidates asked of each library for each set of words
SHORTEST = 0.6         # a clip shorter than this share of the shot is left out (when the library says how long it is)
API_SOURCES = ("pexels", "pixabay")


def cid_of(project_id: str, key: str, c: dict) -> str:
    return "stk_" + hashlib.sha1(f"{project_id}|{key}|{c['source']}|{c['source_id']}".encode()).hexdigest()[:20]


def grab_frame(url: str, out: Path, *, seconds: float = 1.0, timeout: float = 25.0) -> Path | None:
    """One picture from a video on the web, read from its start by ffmpeg without downloading it: for a candidate whose library
    gives no preview picture."""
    from nexora.adapters.stock_api import resolve_public
    try:
        url = resolve_public(url)                      # redirects followed and checked here; ffmpeg gets the final public address
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-protocol_whitelist", "https,tls,tcp", "-ss", str(seconds), "-i", url, "-frames:v", "1", "-vf", "scale=640:-2", str(out)],
                       capture_output=True, timeout=timeout, check=True)
        return out if out.is_file() else None
    except (AdapterError, OSError, subprocess.SubprocessError):
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class StockScout:
    def __init__(self, db_path: str | Path, adapters, tmp_dir: str | Path, *, fetch=None, frame=None):
        self._db = db.LocalConnections(db_path)
        with db.write(self._db.get()) as c:
            for statement in SCHEMA.strip().split(";\n"):
                c.execute(statement)
        self._adapters, self._tmp = adapters, Path(tmp_dir)
        if fetch is None:
            from nexora.adapters.stock_api import fetch_public
            fetch = lambda url, path: fetch_public(url, path, max_bytes=8_000_000, timeout=20)
        self._fetch, self._frame = fetch, frame or grab_frame

    @property
    def _conn(self):
        return self._db.get()

    def _has(self, name: str) -> bool:
        return any(c.name == name for c in self._adapters.describe())

    # ------------------------------------------------------------------------------------------------------------- words
    def keywords(self, line: str) -> dict:
        """What to search for: English from precise to broad, Vietnamese, and the names in the line as written."""
        try:
            out = self._adapters.submit("model", Request("chat", params={"prompt": KEYWORDS_PROMPT.format(line=line), "json": True, "max_tokens": 160})).outputs["json"]
        except (AdapterError, KeyError, TypeError):
            out = {}
        clean = lambda xs: [str(x).strip() for x in (xs if isinstance(xs, list) else [xs] if xs else []) if str(x).strip()]
        return {"en": clean(out.get("en"))[:3], "vi": clean(out.get("vi"))[:2] or [line[:80]], "names": clean(out.get("names"))[:3]}

    def _rounds(self, kw: dict) -> list[dict]:
        names = " ".join(kw["names"])
        rounds = []
        for i in range(ROUNDS):
            en = kw["en"][i] if i < len(kw["en"]) else None
            vi = kw["vi"][i] if i < len(kw["vi"]) else None
            if en is None and vi is None:
                break
            rounds.append({"en": en, "vi": vi, "names": names if i == 0 else ""})
        return rounds

    def _search(self, words: dict, sources: list[str] | None) -> list[dict]:
        """One round of searching: each library in the words it takes. A library that fails leaves the others."""
        found = []
        if self._has("stock"):
            queries = [q for q in (words["en"] or words["vi"], words["names"]) if q]      # without English words, the Vietnamese
            keyless = [s for s in (sources or []) if s not in API_SOURCES] or None
            if queries:
                try:
                    found += self._adapters.submit("stock", Request("candidates", inputs={"queries": queries}, params={"per_query": PER_QUERY, **({"sources": keyless} if keyless else {})},
                                                                    privacy_class=PrivacyClass.CLOUD_ALLOWED)).outputs["candidates"]
                except AdapterError as err:
                    if err.code is ErrorCode.AUTH:
                        raise                                  # privacy mode: nothing may leave the machine, and the operator is told
        if self._has("stock_api"):
            wanted = [s for s in (sources or API_SOURCES) if s in API_SOURCES] or list(API_SOURCES)
            for lang, query in (("vi", words["vi"]), ("en", words["en"])):
                if not query:
                    continue
                try:
                    found += self._adapters.submit("stock_api", Request("candidates", inputs={"queries": [query]}, params={"lang": lang, "per_query": PER_QUERY, "sources": wanted},
                                                                        privacy_class=PrivacyClass.CLOUD_ALLOWED)).outputs["candidates"]
                except AdapterError as err:
                    if err.code is ErrorCode.AUTH:
                        raise                                  # privacy mode: nothing may leave the machine, and the operator is told
        return found

    # ----------------------------------------------------------------------------------------------------------- judging
    def _preview(self, project_id: str, cid: str, c: dict) -> Path | None:
        out = self._tmp / project_id / f"{cid}.jpg"
        if out.is_file():
            return out
        if c.get("thumbnail_url"):
            try:
                return self._fetch(c["thumbnail_url"], out)
            except AdapterError:
                pass
        url = c.get("preview_url") or c.get("download_url")
        return self._frame(url, out) if url else None

    def _siglip(self, items: list[dict], text: str) -> None:
        pictured = [x for x in items if x["thumb"]]
        if not pictured or not self._has("picture_text"):
            return
        try:
            images = self._adapters.submit("picture_text", Request("images", inputs={"images": [x["thumb"] for x in pictured]})).outputs["vectors"]
            words = self._adapters.submit("picture_text", Request("texts", inputs={"texts": [text]})).outputs["vectors"][0]
        except (AdapterError, KeyError, IndexError):
            return
        for x, v in zip(pictured, images):
            x["siglip"] = round(cosine(v, words), 4)

    def _look(self, x: dict, line: str) -> None:
        try:
            out = self._adapters.submit("model", Request("describe", inputs={"images": [x["thumb"]]}, params={
                "task": "judge", "line": line, "candidate_text": x.get("tags", ""), "max_tokens": 220, "prompt": JUDGE_PROMPT.format(line=line)})).outputs["json"]
            x["look"], x["why"] = max(0, min(10, int(float(out.get("phu_hop", 0))))), str(out.get("ly_do", "")).strip()
        except (AdapterError, KeyError, TypeError, ValueError):
            x["look"], x["why"] = None, "Chưa chấm kỹ: mô hình nhìn không trả lời"

    @staticmethod
    def _rank(x: dict) -> float:
        return (x["look"] if x.get("look") is not None else -1) * 1000 + (x.get("siglip") or 0) * 100

    def find(self, project_id: str, key: str, line: str, *, seconds: float = 0.0, sources: list[str] | None = None) -> list[dict]:
        """Candidates for one line (`key`: the shot they are for), judged on their previews, best first; nothing downloaded.
        A new search for the same shot replaces the candidates it had."""
        kw = self.keywords(line)
        seen, kept = set(), []
        for words in self._rounds(kw):
            fresh = []
            for c in self._search(words, sources):
                ident = (c["source"], c["source_id"])
                if ident in seen or not c.get("download_url"):
                    continue
                if c.get("duration") and seconds and c["duration"] < SHORTEST * seconds:
                    continue
                seen.add(ident)
                cid = cid_of(project_id, key, c)
                thumb = self._preview(project_id, cid, c)
                fresh.append({**c, "cid": cid, "project_id": project_id, "key": key, "line": line, "thumb": str(thumb) if thumb else None,
                              "siglip": 0.0, "look": None, "why": "", "words": words})
            self._siglip(fresh, " ".join(w for w in (words["en"], words["names"]) if w) or line)
            fresh.sort(key=lambda x: x["siglip"], reverse=True)
            for x in fresh[:LOOKED]:
                if x["thumb"]:
                    self._look(x, line)
            kept += fresh
            if any(x["look"] is not None and x["look"] >= LOOK_PASS for x in fresh):
                break
        kept = sorted(kept, key=self._rank, reverse=True)[:KEPT]
        now = time.time()
        with db.write(self._conn) as c:
            c.execute("DELETE FROM stock_candidates WHERE project_id = ? AND key = ?", (project_id, key))
            for x in kept:
                c.execute("INSERT OR REPLACE INTO stock_candidates (cid, project_id, key, data, rank, created_at) VALUES (?,?,?,?,?,?)",
                          (x["cid"], project_id, key, json.dumps(x, ensure_ascii=False), self._rank(x), now))
        return kept

    # ----------------------------------------------------------------------------------------------------------- reading
    def options(self, project_id: str, key: str) -> list[dict]:
        rows = self._conn.execute("SELECT data FROM stock_candidates WHERE project_id = ? AND key = ? ORDER BY rank DESC", (project_id, key)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def candidate(self, cid: str) -> dict | None:
        row = self._conn.execute("SELECT data FROM stock_candidates WHERE cid = ?", (cid,)).fetchone()
        return json.loads(row["data"]) if row else None

    def best(self, project_id: str, key: str, *, avoid: set[str] = frozenset()) -> dict | None:
        """The best candidate that passes the vision model's look and is not one already chosen next to it (`avoid`: source:id)."""
        return next((x for x in self.options(project_id, key) if x.get("look") is not None and x["look"] >= LOOK_PASS
                     and f"{x['source']}:{x['source_id']}" not in avoid), None)

    def fetch(self, cid: str, out_dir: str | Path) -> Path:
        """Download one candidate, the largest file its library gives."""
        c = self.candidate(cid)
        if c is None:
            raise LookupError(cid)
        name = "stock_api" if c["source"] in API_SOURCES else "stock"
        got = self._adapters.submit(name, Request("download", inputs={"candidate": c}, params={"out_dir": str(out_dir)},
                                                  privacy_class=PrivacyClass.CLOUD_ALLOWED, deadline_seconds=900))
        return Path(got.files[0])

    def forget(self, project_id: str) -> int:
        """A project's candidates and their previews, gone once its storyboard is approved: none of them was downloaded."""
        with db.write(self._conn) as c:
            gone = c.execute("DELETE FROM stock_candidates WHERE project_id = ?", (project_id,)).rowcount
        shutil.rmtree(self._tmp / project_id, ignore_errors=True)
        return gone
