"""Publishing, and learning from what was published (design v4.0, section 21).

The ledger holds one row for every time a cut was sent to a destination. A cut is never sent to the same destination
twice: the second request finds the first row. When a send ends without a clear answer, the row says so, and the
destination is asked what happened before anything is sent again.

Where the system has no account on a platform, the operator uploads by hand and records the address here; the row,
the figures taken at set marks afterwards, and the experiments built on them are the same either way.
"""
import json
import statistics
import time
from pathlib import Path

from nexora.core import db
from nexora.core.adapter import RETRYABLE, AdapterError, AdapterRegistry, ErrorCode, PrivacyClass, Request
from nexora.core.ids import new_id
from nexora.core.projects import ProjectStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (publication_id TEXT PRIMARY KEY, render_id TEXT NOT NULL, project_id TEXT NOT NULL, target TEXT NOT NULL, variant TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, external_ref TEXT, url TEXT, title TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0, manual INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL, published_at REAL);
CREATE TABLE IF NOT EXISTS metric_snapshots (snapshot_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL, at REAL NOT NULL, hours REAL NOT NULL, figures TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS experiments (experiment_id TEXT PRIMARY KEY, question TEXT NOT NULL, metric TEXT NOT NULL, variants TEXT NOT NULL, created_at REAL NOT NULL, closed_at REAL, conclusion TEXT);
"""
PLATFORMS = {"youtube": "YouTube", "tiktok": "TikTok", "facebook": "Facebook", "instagram": "Instagram"}     # no account is connected: the operator uploads and records the address
MARKS = (1, 24, 72, 168)                 # hours after publishing at which figures are taken
FIGURES = ("views", "likes", "comments", "shares", "watch_seconds")
MIN_LEAD = 0.2                           # a variant must lead by this share before the difference is called
MIN_HOURS = 24                           # and both must have been out at least this long
MIN_HISTORY = 3                          # earlier videos needed before a forecast is offered


class Publishing:
    def __init__(self, db_path: str | Path, projects: ProjectStore, adapters: AdapterRegistry, package, *, notify=None):
        self._db, self._projects, self._adapters = db.LocalConnections(db_path), projects, adapters
        self._package, self._notify = package, notify            # package(render_id) -> dict | None; notify(kind, reason)
        with db.write(self._conn) as c:
            for statement in SCHEMA.strip().split(";\n"):
                c.execute(statement)

    @property
    def _conn(self):
        return self._db.get()

    # ------------------------------------------------------------------ the ledger
    def targets(self) -> list[dict]:
        own = [{"target": c.name, "label": "Thư mục xuất bản" if c.name == "publish.folder" else c.name.partition(".")[2], "manual": False}
               for c in self._adapters.describe() if c.name.startswith("publish.")]
        return own + [{"target": key, "label": name, "manual": True} for key, name in PLATFORMS.items()]

    def _row(self, row) -> dict:
        out = dict(row)
        out["manual"] = bool(out["manual"])
        out["snapshots"] = [{**dict(s), "figures": json.loads(s["figures"])} for s in
                            self._conn.execute("SELECT * FROM metric_snapshots WHERE publication_id = ? ORDER BY at", (out["publication_id"],))]
        return out

    def publication(self, publication_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM publications WHERE publication_id = ?", (publication_id,)).fetchone()
        return self._row(row) if row else None

    def publications(self, *, project_id: str | None = None) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM publications WHERE (? IS NULL OR project_id = ?) ORDER BY created_at DESC, publication_id DESC", (project_id, project_id))
        return [self._row(r) for r in rows]

    def _open(self, render_id: str, target: str, variant: str, *, manual: bool) -> tuple[dict, bool]:
        """The ledger row for this cut at this destination: the existing one, or a new one. Returns (row, created)."""
        render = self._projects.render(render_id)
        package = self._package(render_id)
        if render is None or package is None:
            raise ValueError("no_package")
        key = f"{render_id}:{target}:{variant}"
        with db.write(self._conn) as c:
            row = c.execute("SELECT * FROM publications WHERE idempotency_key = ?", (key,)).fetchone()
            if row:
                return self._row(row), False
            publication_id = new_id("pub")
            c.execute("INSERT INTO publications (publication_id, render_id, project_id, target, variant, idempotency_key, status, title, manual, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (publication_id, render_id, render["project_id"], target, variant, key, "pending", package["title"], int(manual), time.time()))
        return self.publication(publication_id), True

    def _set(self, publication_id: str, **fields) -> dict:
        with db.write(self._conn) as c:
            for key, value in fields.items():
                c.execute(f"UPDATE publications SET {key} = ? WHERE publication_id = ?", (value, publication_id))
        return self.publication(publication_id)

    def publish(self, render_id: str, target: str, *, variant: str = "") -> dict:
        """Send a packaged cut to a destination the system can reach. Sending the same cut to the same place again returns the
        first publication; one whose outcome was never learned is settled with the destination first."""
        if target not in {t["target"] for t in self.targets() if not t["manual"]}:
            raise ValueError("unknown_target")
        row, _ = self._open(render_id, target, variant, manual=False)
        if row["status"] == "published":
            return row
        if row["status"] in ("unknown", "publishing"):
            row = self.reconcile(row["publication_id"])
            if row["status"] == "published":
                return row
        package = self._package(render_id)
        files = [package["video"], package["captions"], package["thumbnail"], *(package.get("translations") or {}).values()]
        request = Request("publish", inputs={"folder": package["folder"], "files": files, "title": package["title"], "description": package["description"]},
                          idempotency_key=row["idempotency_key"], privacy_class=PrivacyClass.CLOUD_ALLOWED)         # a publication is meant to leave this machine
        self._set(row["publication_id"], status="publishing", attempts=row["attempts"] + 1, error=None)
        try:
            result = self._adapters.submit(target, request)
        except AdapterError as err:
            # A send that timed out or lost its connection may have arrived. Saying "failed" would invite a second copy.
            unclear = err.code in RETRYABLE or err.code is ErrorCode.TIMEOUT
            return self._set(row["publication_id"], status="unknown" if unclear else "failed", error=err.message or err.code.value)
        return self._set(row["publication_id"], status="published", external_ref=result.external_ref, url=result.outputs.get("url"), published_at=time.time())

    def reconcile(self, publication_id: str) -> dict:
        """Ask the destination what became of a publication whose outcome is not known."""
        row = self.publication(publication_id)
        if row is None or row["manual"] or row["status"] == "published":
            return row
        try:
            found = self._adapters.reconcile(row["target"], Request("publish", idempotency_key=row["idempotency_key"]))
        except AdapterError as err:
            return self._set(publication_id, status="unknown", error=err.message or err.code.value)
        if found is None:
            return self._set(publication_id, status="failed", error="Đích đến không có bản này: lần gửi trước chưa tới nơi.")
        return self._set(publication_id, status="published", external_ref=found.external_ref, url=found.outputs.get("url"), published_at=row["published_at"] or time.time(), error=None)

    def record_manual(self, render_id: str, platform: str, url: str, *, variant: str = "", published_at: float | None = None) -> dict:
        """The operator uploaded this cut by hand: keep where it went, so that it is measured like any other publication."""
        if platform not in PLATFORMS:
            raise ValueError("unknown_target")
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("bad_url")
        row, created = self._open(render_id, platform, variant, manual=True)
        if not created and row["status"] == "published":
            return row                                    # already on record: one upload, one row
        return self._set(row["publication_id"], status="published", url=url.strip(), published_at=published_at or time.time())

    # ------------------------------------------------------------------ figures at set marks
    def add_snapshot(self, publication_id: str, figures: dict, *, at: float | None = None) -> dict:
        row = self.publication(publication_id)
        if row is None or row["status"] != "published":
            raise ValueError("not_published")
        clean = {}
        for key in FIGURES:
            if figures.get(key) not in (None, ""):
                clean[key] = max(0.0, float(figures[key]))
        if not clean:
            raise ValueError("no_figures")
        at = at or time.time()
        with db.write(self._conn) as c:
            c.execute("INSERT INTO metric_snapshots (snapshot_id, publication_id, at, hours, figures) VALUES (?,?,?,?,?)",
                      (new_id("mts"), publication_id, at, round(max(0.0, at - row["published_at"]) / 3600, 2), json.dumps(clean)))
        return self.publication(publication_id)

    def due(self, *, now: float | None = None) -> list[dict]:
        """Publications that have passed a mark without figures taken for it. Each is announced once."""
        now, out = now or time.time(), []
        for row in self.publications():
            if row["status"] != "published":
                continue
            age = (now - row["published_at"]) / 3600
            taken = [s["hours"] for s in row["snapshots"]]
            for i, mark in enumerate(MARKS):
                nxt = MARKS[i + 1] if i + 1 < len(MARKS) else float("inf")
                if age >= mark and not any(mark <= h < nxt for h in taken) and age < nxt:
                    out.append({"publication_id": row["publication_id"], "title": row["title"], "target": row["target"], "mark": mark, "url": row["url"]})
                    seen_key = f"metrics_due:{row['publication_id']}:{mark}"
                    with db.write(self._conn) as c:
                        fresh = c.execute("SELECT 1 FROM settings WHERE key = ?", (seen_key,)).fetchone() is None
                        if fresh:
                            c.execute("INSERT INTO settings (key, value) VALUES (?, '1')", (seen_key,))
                    if fresh and self._notify:
                        self._notify("metrics_due", f"{row['title']} ({mark} giờ)")
        return out

    def _at(self, row: dict, metric: str, hours: float) -> float | None:
        """The figure at the last snapshot taken no later than `hours` after publishing."""
        usable = [s for s in row["snapshots"] if s["hours"] <= hours + 0.5 and metric in s["figures"]]
        return usable[-1]["figures"][metric] if usable else None

    def forecast(self, publication_id: str, *, metric: str = "views") -> dict:
        """Where this video may stand after a week, read off how the operator's earlier videos grew from the same point.
        Offered only when there are enough of them; it is a ratio of medians, not a model."""
        row = self.publication(publication_id)
        own = [s for s in row["snapshots"] if metric in s["figures"]]
        if not own:
            return {"ready": False, "reason": "Chưa có số liệu nào của video này."}
        now_hours, now_value = own[-1]["hours"], own[-1]["figures"][metric]
        if now_hours >= MARKS[-1]:
            return {"ready": False, "reason": "Video đã qua mốc một tuần."}
        ratios = []
        for other in self.publications():
            if other["publication_id"] == publication_id:
                continue
            early, week = self._at(other, metric, max(now_hours, 1)), self._at(other, metric, MARKS[-1])
            last = max((s["hours"] for s in other["snapshots"]), default=0)
            if early and week and last >= MARKS[-1] - 24:
                ratios.append(week / early)
        if len(ratios) < MIN_HISTORY:
            return {"ready": False, "reason": f"Cần ít nhất {MIN_HISTORY} video trước đó có số liệu tới một tuần; hiện có {len(ratios)}."}
        ratio = statistics.median(ratios)
        return {"ready": True, "metric": metric, "from_hours": now_hours, "from_value": now_value, "week": round(now_value * ratio), "based_on": len(ratios),
                "low": round(now_value * min(ratios)), "high": round(now_value * max(ratios))}

    def breakdown(self, *, metric: str = "views", hours: float = 24) -> list[dict]:
        """Figures at one mark grouped by what the videos have in common. These are things that went together, not causes:
        with a handful of videos, any of them could be chance."""
        groups: dict[tuple[str, str], list[float]] = {}
        for row in self.publications():
            value = self._at(row, metric, hours)
            render = self._projects.render(row["render_id"])
            if value is None or render is None:
                continue
            seconds = render["qc"].get("duration") or 0
            for kind, name in (("Khung hình", {"landscape": "Ngang", "portrait": "Dọc", "square": "Vuông"}.get(render["qc"].get("format"), "Khác")),
                               ("Độ dài", "Dưới 30 giây" if seconds < 30 else "30 đến 90 giây" if seconds < 90 else "Trên 90 giây"), ("Nơi đăng", row["target"])):
                groups.setdefault((kind, name), []).append(value)
        return [{"kind": kind, "name": name, "videos": len(values), "median": statistics.median(values)} for (kind, name), values in sorted(groups.items())]

    # ------------------------------------------------------------------ experiments
    def create_experiment(self, question: str, publication_ids: list[str], *, metric: str = "views", labels: list[str] | None = None) -> dict:
        rows = [self.publication(p) for p in publication_ids]
        if len(rows) < 2 or any(r is None for r in rows) or len(set(publication_ids)) != len(publication_ids) or metric not in FIGURES or not question.strip():
            raise ValueError("an experiment needs a question, a known figure and at least two different publications")
        variants = [{"publication_id": r["publication_id"], "label": (labels or [])[i] if labels and i < len(labels) and labels[i] else chr(65 + i)} for i, r in enumerate(rows)]
        experiment_id = new_id("exp")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO experiments (experiment_id, question, metric, variants, created_at) VALUES (?,?,?,?,?)",
                      (experiment_id, question.strip(), metric, json.dumps(variants, ensure_ascii=False), time.time()))
        return self.experiment(experiment_id)

    def experiment(self, experiment_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)).fetchone()
        if row is None:
            return None
        out = {**dict(row), "variants": json.loads(row["variants"])}
        pubs = [self.publication(v["publication_id"]) for v in out["variants"]]
        # Variants are compared at the same age: the latest mark that every one of them has reached with figures.
        reached = [max((s["hours"] for s in p["snapshots"] if out["metric"] in s["figures"]), default=0) for p in pubs]
        common = min(reached) if reached else 0
        for v, p in zip(out["variants"], pubs):
            v.update(title=p["title"], target=p["target"], url=p["url"], value=self._at(p, out["metric"], common) if common else None)
        values = [v["value"] for v in out["variants"]]
        out["compared_at_hours"] = common
        if common < MIN_HOURS or any(v is None for v in values):
            out["verdict"] = {"decided": False, "text": f"Chưa đủ để kết luận: mọi biến thể cần có số liệu sau ít nhất {MIN_HOURS} giờ."}
        else:
            ranked = sorted(out["variants"], key=lambda v: -v["value"])
            lead = (ranked[0]["value"] - ranked[1]["value"]) / ranked[1]["value"] if ranked[1]["value"] else float("inf")
            out["verdict"] = ({"decided": True, "leader": ranked[0]["label"], "lead": None if lead == float("inf") else round(lead, 3),
                               "text": f"Biến thể {ranked[0]['label']} dẫn trước ở mốc {common:.0f} giờ. Đây là một lần đo trên một cặp video, chưa phải quy luật."}
                              if lead >= MIN_LEAD else {"decided": False, "text": f"Hai biến thể gần nhau (chênh dưới {MIN_LEAD:.0%}) ở mốc {common:.0f} giờ: chưa nói được bên nào hơn."})
        return out

    def experiments(self) -> list[dict]:
        return [self.experiment(r[0]) for r in self._conn.execute("SELECT experiment_id FROM experiments ORDER BY created_at DESC")]

    def close_experiment(self, experiment_id: str, conclusion: str) -> dict:
        with db.write(self._conn) as c:
            c.execute("UPDATE experiments SET closed_at = ?, conclusion = ? WHERE experiment_id = ?", (time.time(), conclusion.strip(), experiment_id))
        return self.experiment(experiment_id)
