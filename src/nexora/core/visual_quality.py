"""Visual Quality: what is known about how a picture looks, and the recipes that make it look right (design 2026-10-16).

A **subject** is what is worked on: an asset of the library (its asset id) or any file given to the engine (a job id,
`vqj_…`). For each subject the engine keeps:

- a **profile**: what the source is (container, codec, depth, rate, colour encoding, camera) and what it looks like (flat
  log, clipped, noisy, soft, blocky), with how sure it is and where its tags and its picture disagree;
- **defects**: what is wrong, where and how badly, shot by shot;
- **recipes**: ordered steps per shot that put it right, versioned; only an approved recipe is ever applied;
- **metrics**: what each recipe did, measured before and after;
- **previews**: a few seconds before and after, to look at before approving.

Only the Visual Quality domain (`nexora.modules.visual_quality`) writes, through `nexora.core.visual_quality_store`;
editing, the library and every other reader use `VisualQuality`. The import contracts in pyproject.toml hold this.

The recipe is applied where footage is used: a step the FFmpeg filter graph can do is turned into filters here
(`filters_for`), so that a cut or an extract adds them to its own graph; a step that needs another tool (Apple's frame
processors, Gyroflow, a model) has been rendered by the engine into a prepared file beforehand (`prepared_for`).
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path

from nexora.core import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS vq_subjects (subject TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL, checksum TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS vq_profiles (subject TEXT PRIMARY KEY, data TEXT NOT NULL, analyzer TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS vq_defects (subject TEXT NOT NULL, t_start REAL NOT NULL, t_end REAL NOT NULL, kind TEXT NOT NULL, severity REAL NOT NULL,
    data TEXT NOT NULL DEFAULT '{}', analyzer TEXT NOT NULL, PRIMARY KEY (subject, t_start, kind));
CREATE TABLE IF NOT EXISTS vq_recipes (recipe_id TEXT PRIMARY KEY, subject TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL,
    decided_by TEXT, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS vq_recipes_subject ON vq_recipes (subject, version);
CREATE TABLE IF NOT EXISTS vq_metrics (recipe_id TEXT NOT NULL, t_start REAL NOT NULL, t_end REAL NOT NULL, metric TEXT NOT NULL, before REAL, after REAL,
    PRIMARY KEY (recipe_id, t_start, metric));
CREATE TABLE IF NOT EXISTS vq_previews (preview_id TEXT PRIMARY KEY, recipe_id TEXT NOT NULL, t REAL NOT NULL, seconds REAL NOT NULL, data TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS vq_prepared (recipe_id TEXT NOT NULL, t_start REAL NOT NULL, t_end REAL NOT NULL, path TEXT NOT NULL, at REAL NOT NULL,
    PRIMARY KEY (recipe_id, t_start));
CREATE TABLE IF NOT EXISTS vq_requests (request_id TEXT PRIMARY KEY, subject TEXT NOT NULL, kind TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL, result TEXT, at REAL NOT NULL)
"""

STATUSES = ("proposed", "approved", "rejected")


def ensure_schema(db_path: str | Path) -> None:
    conn = db.LocalConnections(db_path).get()
    with db.write(conn) as c:
        for statement in SCHEMA.strip().split(";\n"):
            if statement.strip():
                c.execute(statement)


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    subject: str
    version: int
    data: dict
    status: str
    decided_by: str | None
    at: float

    @property
    def shots(self) -> list[dict]:
        return self.data.get("shots", [])


# ---------------------------------------------------------------------------------------------- steps as FFmpeg filters
def _num(x, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def step_filters(step: dict) -> list[str] | None:
    """The FFmpeg filters that do one step of a recipe, or None when the step needs another tool (a prepared file)."""
    op, p = step.get("op"), step.get("params") or {}
    if step.get("tier", "ffmpeg") != "ffmpeg":
        return None
    if op == "deinterlace":
        return [f"bwdif=mode={'send_field' if p.get('double_rate') else 'send_frame'}:parity=auto:deint=all"]
    if op == "ivtc":
        return ["fieldmatch", "yadif=deint=interlaced", "decimate"]
    if op == "constant_rate":
        return [f"fps={_num(p.get('fps', 30), 1, 240):g}"]
    if op == "deblock":
        return [f"deblock=filter=strong:block={int(p.get('block', 8))}"]
    if op == "deband":
        # Gentle and without blur: on a frame with little real banding, blur=1 and a high threshold cost more naturalness
        # than they give (measured on a web interview, NIQE 7.5 → 9.7 at 0.02 with blur).
        t = _num(p.get("threshold", 0.02), 0.003, 0.06)
        return [f"deband=1thr={t:.3f}:2thr={t:.3f}:3thr={t:.3f}:range={int(p.get('range', 24))}:blur={1 if p.get('blur') else 0}"]
    if op == "tonemap":
        # HDR to SDR: linear light, the BT.709 primaries, a tone curve, then the BT.709 transfer.
        return [f"zscale=t=linear:npl={int(p.get('peak', 100))}", "format=gbrpf32le", "zscale=p=bt709",
                f"tonemap=tonemap={p.get('curve', 'hable')}:desat=0", "zscale=t=bt709:m=bt709:r=tv", "format=yuv420p10le"]
    if op == "color_transform":
        lut = str(p["lut"]).replace("\\", "/").replace(":", "\\:")
        return [f"lut3d=file='{lut}':interp=tetrahedral"]
    if op in ("levels", "match") and p.get("lut"):
        # Baked by the engine into a LUT (visual_quality.plan.levels_lut, visual_quality.match.bake): exact at any depth.
        lut = str(p["lut"]).replace("\\", "/").replace(":", "\\:")
        return [f"lut3d=file='{lut}':interp=tetrahedral"]
    if op == "levels":
        # Without a baked LUT (an older recipe): FFmpeg's filters, on 16-bit RGB, since colorlevels blacks out 10-bit planar RGB.
        # Black and white points, and white balance, per channel (0..1 of the range), then the midtones.
        lo, hi = p.get("black", [0, 0, 0]), p.get("white", [1, 1, 1])
        f = ["format=gbrp16le", ("colorlevels=" + ":".join(f"{c}imin={_num(a, 0, 0.5):.4f}:{c}imax={_num(b, 0.5, 1):.4f}" for c, a, b in zip("rgb", lo, hi)))]
        eq = []
        if abs(float(p.get("gamma", 1.0)) - 1.0) > 1e-3:
            eq.append(f"gamma={_num(p['gamma'], 0.5, 2.0):.3f}")
        if abs(float(p.get("saturation", 1.0)) - 1.0) > 1e-3:
            eq.append(f"saturation={_num(p['saturation'], 0.5, 1.6):.3f}")
        if abs(float(p.get("contrast", 1.0)) - 1.0) > 1e-3:
            eq.append(f"contrast={_num(p['contrast'], 0.7, 1.4):.3f}")
        return f + ([f"eq={':'.join(eq)}"] if eq else [])
    if op == "denoise":
        # Set by the noise measured (`sigma`, 0..255), not by a fixed strength: measured on a clean frame of the library with
        # noise added, nlmeans at s ≈ 1.1 × sigma took PSNR from 26.6 to 36.2 (sigma 12) and from 20.3 to 32.0 (sigma 25),
        # where a fixed small s did nothing (Visual Quality benchmark, 2026-10-17). `strength` scales it (0..2).
        sigma = _num(p.get("sigma", 4.0), 0.5, 40.0) * _num(p.get("strength", 1.0), 0.0, 2.0)
        if p.get("method") == "nlmeans":
            return [f"nlmeans=s={_num(1.1 * sigma, 1.0, 30.0):.2f}:p=7:r=15"]
        return [f"hqdn3d={1.2 * sigma:.2f}:{0.9 * sigma:.2f}:{1.8 * sigma:.2f}:{1.35 * sigma:.2f}"]
    if op == "sharpen":
        return [f"cas=strength={_num(p.get('strength', 0.3), 0.0, 1.0):.3f}"]
    if op == "deflicker":
        return [f"deflicker=size={int(_num(p.get('size', 5), 2, 129))}:mode={p.get('mode', 'am')}"]
    if op == "stabilise":
        return None                                  # two passes (vidstab) or Gyroflow: always a prepared file
    if op == "upscale":
        f = int(p.get("factor", 2))
        return [f"scale=iw*{f}:ih*{f}:flags=lanczos"]
    if op == "interpolate":
        return [f"minterpolate=fps={_num(p.get('fps', 60), 1, 240):g}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"]
    if op == "rotate":
        return {90: ["transpose=1"], 180: ["transpose=1,transpose=1"], 270: ["transpose=2"]}.get(int(p.get("degrees", 0)) % 360, [])
    return None


def filters_of(steps: list[dict]) -> list[str] | None:
    """The filter chain for a list of steps, or None when any of them needs a prepared file."""
    out: list[str] = []
    for step in steps:
        if step.get("off"):
            continue
        f = step_filters(step)
        if f is None:
            return None
        out += f
    return out


class VisualQuality:
    """Reads what Visual Quality knows and has decided. Used by editing, the library, the API and every other reader."""

    def __init__(self, db_path: str | Path):
        self._db = db.LocalConnections(db_path)
        ensure_schema(db_path)

    @property
    def _conn(self):
        return self._db.get()

    # -------------------------------------------------------------------------------------------------------- subjects
    def subject(self, subject: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM vq_subjects WHERE subject = ?", (subject,)).fetchone()
        return dict(row) if row else None

    def profile(self, subject: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM vq_profiles WHERE subject = ?", (subject,)).fetchone()
        return {**json.loads(row["data"]), "analyzer": row["analyzer"], "at": row["at"]} if row else None

    def defects(self, subject: str) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM vq_defects WHERE subject = ? ORDER BY t_start, kind", (subject,))
        return [{"t_start": r["t_start"], "t_end": r["t_end"], "kind": r["kind"], "severity": r["severity"], **json.loads(r["data"])} for r in rows]

    # --------------------------------------------------------------------------------------------------------- recipes
    def _recipe(self, row) -> Recipe:
        return Recipe(row["recipe_id"], row["subject"], row["version"], json.loads(row["data"]), row["status"], row["decided_by"], row["at"])

    def recipes(self, subject: str) -> list[Recipe]:
        return [self._recipe(r) for r in self._conn.execute("SELECT * FROM vq_recipes WHERE subject = ? ORDER BY version DESC", (subject,))]

    def recipe(self, subject: str, *, status: str | None = None) -> Recipe | None:
        """The newest recipe of a subject, or the newest with a given status."""
        q, args = "SELECT * FROM vq_recipes WHERE subject = ?", [subject]
        if status:
            q += " AND status = ?"; args.append(status)
        row = self._conn.execute(q + " ORDER BY version DESC LIMIT 1", args).fetchone()
        return self._recipe(row) if row else None

    def by_id(self, recipe_id: str) -> Recipe | None:
        row = self._conn.execute("SELECT * FROM vq_recipes WHERE recipe_id = ?", (recipe_id,)).fetchone()
        return self._recipe(row) if row else None

    def metrics(self, recipe_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM vq_metrics WHERE recipe_id = ? ORDER BY t_start, metric", (recipe_id,))
        return [dict(r) for r in rows]

    def previews(self, recipe_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM vq_previews WHERE recipe_id = ? ORDER BY at DESC", (recipe_id,))
        return [{"preview_id": r["preview_id"], "t": r["t"], "seconds": r["seconds"], **json.loads(r["data"]), "at": r["at"]} for r in rows]

    # --------------------------------------------------------------------------------------- what a cut or extract uses
    def steps_for(self, subject: str, t_in: float, t_out: float) -> tuple[Recipe | None, list[dict]]:
        """The approved recipe of a subject and the steps of the shot a stretch lies in (the shot it overlaps most)."""
        recipe = self.recipe(subject, status="approved")
        if recipe is None:
            return None, []
        best, overlap = None, 0.0
        for shot in recipe.shots:
            o = min(t_out, shot["t_end"]) - max(t_in, shot["t_start"])
            if o > overlap:
                best, overlap = shot, o
        return recipe, [s for s in (best or {}).get("steps", []) if not s.get("off")]

    def filters_for(self, subject: str, t_in: float, t_out: float) -> list[str] | None:
        """The filters an approved recipe adds to a stretch: [] when there is none or nothing to do, None when the stretch
        must be taken from a prepared file instead (see `prepared_for`)."""
        recipe, steps = self.steps_for(subject, t_in, t_out)
        if recipe is None:
            return []
        return filters_of(steps)

    def whole_filters(self, subject: str) -> tuple[Recipe | None, list[str]]:
        """Filters an approved recipe puts on a whole file at once: every step when all shots share the same FFmpeg-only steps,
        else the colour steps they all share (a camera's transform is the same in every shot; exposure is not)."""
        recipe = self.recipe(subject, status="approved")
        if recipe is None or not recipe.shots:
            return None, []
        per_shot = [[s for s in shot.get("steps", []) if not s.get("off")] for shot in recipe.shots]
        if all(json.dumps(x, sort_keys=True) == json.dumps(per_shot[0], sort_keys=True) for x in per_shot):
            whole = filters_of(per_shot[0])
            if whole is not None:
                return recipe, whole
        shared = [s for s in per_shot[0] if s.get("op") in ("tonemap", "color_transform")
                  and all(any(json.dumps(s, sort_keys=True) == json.dumps(t, sort_keys=True) for t in x) for x in per_shot)]
        return recipe, filters_of(shared) or []

    def prepared_for(self, subject: str, t_in: float, t_out: float) -> tuple[str, float] | None:
        """A file the engine rendered with the approved recipe that covers a stretch, and where the stretch starts in it."""
        recipe = self.recipe(subject, status="approved")
        if recipe is None:
            return None
        for r in self._conn.execute("SELECT * FROM vq_prepared WHERE recipe_id = ? ORDER BY t_start", (recipe.recipe_id,)):
            if r["t_start"] <= t_in + 1e-3 and t_out <= r["t_end"] + 1e-3 and Path(r["path"]).is_file():
                return r["path"], round(t_in - r["t_start"], 3)
        return None

    def requests(self, subject: str, *, kind: str | None = None, status: str | None = None) -> list[dict]:
        """What was asked of the engine for a subject (a plan with options, a preview at a time, an apply to a file)."""
        q, args = "SELECT * FROM vq_requests WHERE subject = ?", [subject]
        if kind:
            q += " AND kind = ?"; args.append(kind)
        if status:
            q += " AND status = ?"; args.append(status)
        return [{**dict(r), "params": json.loads(r["params"]), "result": json.loads(r["result"]) if r["result"] else None}
                for r in self._conn.execute(q + " ORDER BY at", args)]

    def subjects(self) -> list[dict]:
        """Every subject the engine knows, with what the screens list it by: its newest recipe, its worst defect, its newest
        preview's verdict."""
        out = []
        for row in self._conn.execute("SELECT * FROM vq_subjects ORDER BY created_at DESC"):
            subject = row["subject"]
            recipe = self.recipe(subject)
            prof = self._conn.execute("SELECT data FROM vq_profiles WHERE subject = ?", (subject,)).fetchone()
            prof = json.loads(prof["data"]) if prof else None
            worst = self._conn.execute("SELECT kind, MAX(severity) AS s, COUNT(*) AS n FROM vq_defects WHERE subject = ?", (subject,)).fetchone()
            preview = self._conn.execute("SELECT data FROM vq_previews WHERE recipe_id = ? ORDER BY at DESC LIMIT 1",
                                         (recipe.recipe_id,)).fetchone() if recipe else None
            steps = [s for shot in (recipe.shots if recipe else []) for s in shot.get("steps", []) if not s.get("off")]
            out.append({"subject": subject, "kind": row["kind"], "path": row["path"], "created_at": row["created_at"],
                        "recipe": {"recipe_id": recipe.recipe_id, "version": recipe.version, "status": recipe.status, "at": recipe.at} if recipe else None,
                        "encoding_name": (prof or {}).get("encoding_name"), "content": (prof or {}).get("content"),
                        "still": ((prof or {}).get("technical") or {}).get("kind") == "still" if prof else None,
                        "warnings": len((prof or {}).get("warnings", [])),
                        "defects": worst["n"] if worst else 0, "worst": {"kind": worst["kind"], "severity": round(worst["s"], 3)} if worst and worst["n"] else None,
                        "steps": len(steps), "generative": sum(1 for s in steps if s.get("generative")),
                        "verdict": json.loads(preview["data"]).get("qa", {}).get("verdict") if preview else None})
        return out

    def summary(self, subject: str) -> dict:
        """What the screens show at a glance."""
        recipe = self.recipe(subject)
        approved = self.recipe(subject, status="approved")
        return {"subject": subject, "profile": self.profile(subject), "defects": self.defects(subject),
                # The recipe's own data carries the planner's version under the same key: the version of the recipe comes last.
                "recipe": {**recipe.data, "planner_version": recipe.data.get("version"), "recipe_id": recipe.recipe_id, "version": recipe.version,
                           "status": recipe.status, "decided_by": recipe.decided_by} if recipe else None,
                "approved": approved.recipe_id if approved else None,
                "metrics": self.metrics(recipe.recipe_id) if recipe else [], "previews": self.previews(recipe.recipe_id) if recipe else [],
                "requests": self.requests(subject)[-10:], "at": time.time(),
                "versions": [{"recipe_id": r.recipe_id, "version": r.version, "status": r.status, "decided_by": r.decided_by, "at": r.at,
                              "from": r.data.get("from"), "edited": any(s.get("edited") for shot in r.shots for s in shot.get("steps", []))}
                             for r in self.recipes(subject)]}
