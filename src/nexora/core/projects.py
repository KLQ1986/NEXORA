"""Shared production records: projects, versioned scripts with shots, selections and renders (design v4.0, section 8).

Planning writes scripts, Sourcing writes selections, Edit reads both and writes renders; they meet here, not in each other.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id


@dataclass(frozen=True)
class Shot:
    shot_id: str
    script_id: str
    position: int
    text: str
    scene: str | None = None          # the scene this line belongs to
    brief: str | None = None          # what the picture should show, in the operator's words
    screen_text: str | None = None    # words on screen, when they differ from what is spoken
    target_seconds: float | None = None   # hold the picture at least this long
    sound_cue: str | None = None      # a note for the sound: an effect, a pause, a music change
    is_fact: bool = False             # the line states a fact, so it needs a source
    source: str | None = None         # the title of the source in the project's research that supports it
    fact_check: dict | None = None    # what checking the line against the sources found: verdict, source, quote
    gen: dict = field(default_factory=dict)   # the operator's choices for a generated picture: subject, framing, provider, variation


@dataclass(frozen=True)
class Selection:
    shot_id: str
    status: str                 # proposed, accepted or gap
    asset_id: str | None
    moment_id: str | None
    t_in: float | None
    t_out: float | None
    score: float | None
    reason: str | None
    alternates: list
    decided_by: str
    extras: dict = field(default_factory=dict)      # what rides on a selection: inserts timed to a word, the operator's framing


class ProjectStore:
    def __init__(self, path: str | Path):
        self._db = db.LocalConnections(path)

    @property
    def _conn(self):
        return self._db.get()

    def create_project(self, title: str, *, format: str = "landscape") -> str:
        project_id = new_id("prj")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO projects (project_id, title, format, created_at) VALUES (?,?,?,?)", (project_id, title, format, time.time()))
        return project_id

    def update_project(self, project_id: str, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("title", "format", "music_path", "auto_accept", "style", "narration_dir", "budget_cap", "voice", "music_gain", "template", "profile", "research", "due_date", "bible", "options", "channel")}
        with db.write(self._conn) as c:
            for key, value in allowed.items():
                c.execute(f"UPDATE projects SET {key} = ? WHERE project_id = ?", (value, project_id))

    def projects(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM projects ORDER BY created_at DESC, project_id DESC")]

    def project(self, project_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def save_script(self, project_id: str, lines: list[str]) -> str:
        """A script is never edited in place: saving creates the next version."""
        script_id = new_id("scr")
        with db.write(self._conn) as c:
            version = c.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM scripts WHERE project_id = ?", (project_id,)).fetchone()[0]
            c.execute("INSERT INTO scripts (script_id, project_id, version, created_at) VALUES (?,?,?,?)", (script_id, project_id, version, time.time()))
            # A line starting with "#" names a scene; the lines after it belong to that scene. Notes a line carried in the
            # previous version follow it into the new one, as long as its words are unchanged.
            before = {r["text"]: r for r in c.execute("SELECT s.text, s.brief, s.screen_text, s.target_seconds, s.sound_cue, s.is_fact, s.source, s.fact_check, s.gen FROM shots s JOIN scripts sc USING (script_id) "
                                                      "WHERE sc.project_id = ? AND sc.version = ?", (project_id, version - 1))}
            scene, position = None, 0
            for text in (line.strip() for line in lines if line.strip()):
                if text.startswith("#"):
                    scene = text.lstrip("# ").strip() or None
                    continue
                kept = before.get(text)
                c.execute("INSERT INTO shots (shot_id, script_id, position, text, scene, brief, screen_text, target_seconds, sound_cue, is_fact, source, fact_check, gen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (new_id("sht"), script_id, position, text, scene, *((kept["brief"], kept["screen_text"], kept["target_seconds"], kept["sound_cue"], kept["is_fact"], kept["source"], kept["fact_check"], kept["gen"]) if kept else (None, None, None, None, 0, None, None, None))))
                position += 1
        return script_id

    def annotate_shot(self, shot_id: str, *, brief: str | None = None, screen_text: str | None = None, **more) -> None:
        """Notes on a line that do not change what is spoken, so they do not make a new script version."""
        with db.write(self._conn) as c:
            if brief is not None:
                c.execute("UPDATE shots SET brief = ? WHERE shot_id = ?", (brief.strip() or None, shot_id))
            if screen_text is not None:
                c.execute("UPDATE shots SET screen_text = ? WHERE shot_id = ?", (screen_text.strip() or None, shot_id))
            if "target_seconds" in more:
                c.execute("UPDATE shots SET target_seconds = ? WHERE shot_id = ?", (float(more["target_seconds"]) if more["target_seconds"] not in (None, "") else None, shot_id))
            if "sound_cue" in more:
                c.execute("UPDATE shots SET sound_cue = ? WHERE shot_id = ?", (str(more["sound_cue"] or "").strip() or None, shot_id))
            if "is_fact" in more:
                c.execute("UPDATE shots SET is_fact = ? WHERE shot_id = ?", (int(bool(more["is_fact"])), shot_id))
            if "source" in more:
                c.execute("UPDATE shots SET source = ? WHERE shot_id = ?", (str(more["source"] or "").strip() or None, shot_id))
            if "gen" in more:                              # merged, so that one choice can be changed without restating the others
                row = c.execute("SELECT gen FROM shots WHERE shot_id = ?", (shot_id,)).fetchone()
                current = {**(json.loads(row[0]) if row and row[0] else {}), **(more["gen"] or {})}
                current = {k: v for k, v in current.items() if v not in (None, "")}
                c.execute("UPDATE shots SET gen = ? WHERE shot_id = ?", (json.dumps(current, ensure_ascii=False) if current else None, shot_id))

    def shot(self, shot_id: str) -> Shot | None:
        row = self._conn.execute("SELECT script_id FROM shots WHERE shot_id = ?", (shot_id,)).fetchone()
        return next((s for s in self.script(row[0])["shots"] if s.shot_id == shot_id), None) if row else None

    def reorder(self, script_id: str, order: list[str]) -> str:
        """The same lines in a new order, as the next version of the script. Each line keeps its clip, so nothing has to be matched again."""
        if sorted(order) != sorted(s.shot_id for s in self.script(script_id)["shots"]):
            raise ValueError("the new order must name every shot of the script exactly once")
        return self.revise(script_id, order)

    def revise(self, script_id: str, order: list[str], *, texts: dict[str, str] | None = None, project_id: str | None = None) -> str:
        """The next version of a script made from lines of this one: `order` names the lines to keep, in their new order, and
        `texts` gives new words for some of them. A line whose words are unchanged keeps its clip and everything chosen for it;
        a reworded line keeps its notes but must be matched again. With `project_id` the new script starts another project."""
        old, texts = self.script(script_id), texts or {}
        by_id = {s.shot_id: s for s in old["shots"]}
        if len(set(order)) != len(order) or any(shot_id not in by_id for shot_id in order) or not order:
            raise ValueError("the order must name lines of this script, each at most once")
        target, new_id_ = project_id or old["project_id"], new_id("scr")
        same = all((texts.get(i) or by_id[i].text) == by_id[i].text for i in order) and len(order) == len(by_id)
        with db.write(self._conn) as c:
            version = c.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM scripts WHERE project_id = ?", (target,)).fetchone()[0]
            c.execute("INSERT INTO scripts (script_id, project_id, version, match_approved, created_at) VALUES (?,?,?,?,?)",
                      (new_id_, target, version, int(old["match_approved"] and same), time.time()))
            for position, shot_id in enumerate(order):
                fresh, old_shot = new_id("sht"), by_id[shot_id]
                text = (texts.get(shot_id) or old_shot.text).strip()
                kept = text == old_shot.text
                c.execute("INSERT INTO shots (shot_id, script_id, position, text, scene, brief, screen_text, target_seconds, sound_cue, is_fact, source, fact_check, gen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (fresh, new_id_, position, text, old_shot.scene, old_shot.brief, old_shot.screen_text, old_shot.target_seconds, old_shot.sound_cue,
                           int(old_shot.is_fact and kept), old_shot.source if kept else None,
                           json.dumps(old_shot.fact_check, ensure_ascii=False) if old_shot.fact_check and kept else None, json.dumps(old_shot.gen, ensure_ascii=False) if old_shot.gen else None))
                if not kept:
                    continue
                c.execute("INSERT INTO selections (shot_id, status, asset_id, moment_id, t_in, t_out, score, reason, alternates, decided_by, extras) "
                          "SELECT ?, status, asset_id, moment_id, t_in, t_out, score, reason, alternates, decided_by, extras FROM selections WHERE shot_id = ?", (fresh, shot_id))
                c.execute("INSERT INTO generations (record_id, shot_id, kind, spec, prompt, compiler_version, provider, model, seed, asset_id, created_at, quality) "
                          "SELECT record_id || ?, ?, kind, spec, prompt, compiler_version, provider, model, seed, asset_id, created_at, quality FROM generations WHERE shot_id = ?",
                          (f"-{new_id_[-6:]}", fresh, shot_id))
        return new_id_

    def clone(self, project_id: str, *, title: str, format: str) -> str:
        """The same video in another shape: a new project with this one's script, clips and settings, in another format."""
        source = self.project(project_id)
        new = self.create_project(title, format=format)
        self.update_project(new, **{k: source.get(k) for k in ("music_path", "auto_accept", "style", "narration_dir", "voice", "music_gain", "profile", "research", "bible", "options") if source.get(k) is not None})
        script = self.current_script(project_id)
        if script:
            self.revise(script["script_id"], [s.shot_id for s in script["shots"]], project_id=new)
        return new

    def script(self, script_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM scripts WHERE script_id = ?", (script_id,)).fetchone()
        if row is None:
            return None
        shots = [Shot(r["shot_id"], r["script_id"], r["position"], r["text"], r["scene"], r["brief"], r["screen_text"], r["target_seconds"], r["sound_cue"], bool(r["is_fact"]), r["source"],
                      json.loads(r["fact_check"]) if r["fact_check"] else None, json.loads(r["gen"]) if r["gen"] else {})
                 for r in self._conn.execute("SELECT * FROM shots WHERE script_id = ? ORDER BY position", (script_id,))]
        return {**dict(row), "match_approved": bool(row["match_approved"]), "critique": json.loads(row["critique"]) if row["critique"] else None, "shots": shots}

    def set_fact_check(self, shot_id: str, result: dict | None) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE shots SET fact_check = ? WHERE shot_id = ?", (json.dumps(result, ensure_ascii=False) if result else None, shot_id))

    def set_critique(self, script_id: str, notes: list[dict]) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE scripts SET critique = ? WHERE script_id = ?", (json.dumps(notes, ensure_ascii=False), script_id))

    def used_assets(self) -> dict[str, list[str]]:
        """Which projects use each asset in the current version of their script."""
        rows = self._conn.execute(
            "SELECT DISTINCT sel.asset_id, sc.project_id FROM selections sel JOIN shots sh USING (shot_id) JOIN scripts sc USING (script_id) "
            "WHERE sel.asset_id IS NOT NULL AND sel.status != 'gap' AND sc.version = (SELECT MAX(version) FROM scripts WHERE project_id = sc.project_id)")
        out: dict[str, list[str]] = {}
        for asset_id, project_id in rows:
            out.setdefault(asset_id, []).append(project_id)
        return out

    def script_ids(self, project_id: str) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT script_id FROM scripts WHERE project_id = ? ORDER BY version", (project_id,))]

    def current_script(self, project_id: str) -> dict | None:
        row = self._conn.execute("SELECT script_id FROM scripts WHERE project_id = ? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
        return self.script(row[0]) if row else None

    def set_match_approved(self, script_id: str, approved: bool) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE scripts SET match_approved = ? WHERE script_id = ?", (int(approved), script_id))

    def set_selection(self, shot_id: str, *, status: str, asset_id=None, moment_id=None, t_in=None, t_out=None, score=None,
                      reason=None, alternates=None, decided_by: str = "system") -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO selections (shot_id, status, asset_id, moment_id, t_in, t_out, score, reason, alternates, decided_by) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(shot_id) DO UPDATE SET status=excluded.status, asset_id=excluded.asset_id, "
                      "moment_id=excluded.moment_id, t_in=excluded.t_in, t_out=excluded.t_out, score=excluded.score, reason=excluded.reason, "
                      "alternates=excluded.alternates, decided_by=excluded.decided_by",
                      (shot_id, status, asset_id, moment_id, t_in, t_out, score, reason, json.dumps(alternates or []), decided_by))

    def selection(self, shot_id: str) -> Selection | None:
        row = self._conn.execute("SELECT * FROM selections WHERE shot_id = ?", (shot_id,)).fetchone()
        return Selection(row["shot_id"], row["status"], row["asset_id"], row["moment_id"], row["t_in"], row["t_out"], row["score"],
                         row["reason"], json.loads(row["alternates"]), row["decided_by"], json.loads(row["extras"])) if row else None

    def set_extras(self, shot_id: str, **values) -> None:
        with db.write(self._conn) as c:
            current = json.loads(c.execute("SELECT extras FROM selections WHERE shot_id = ?", (shot_id,)).fetchone()[0])
            current.update(values)
            c.execute("UPDATE selections SET extras = ? WHERE shot_id = ?", (json.dumps(current, ensure_ascii=False), shot_id))

    def selections(self, script_id: str) -> list[Selection]:
        shots = self.script(script_id)["shots"]
        return [s for s in (self.selection(shot.shot_id) for shot in shots) if s is not None]

    def add_generation(self, shot_id: str, *, kind: str, spec: dict, prompt: str, compiler_version: str, provider: str, model: str | None,
                       seed: int | None, asset_id: str | None, quality: dict | None = None) -> str:
        record_id = new_id("gen")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO generations (record_id, shot_id, kind, spec, prompt, compiler_version, provider, model, seed, asset_id, created_at, quality) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (record_id, shot_id, kind, json.dumps(spec, ensure_ascii=False), prompt, compiler_version, provider, model,
                                                         seed, asset_id, time.time(), json.dumps(quality, ensure_ascii=False) if quality else None))
        return record_id

    def generations(self, shot_id: str, *, kind: str | None = None) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM generations WHERE shot_id = ? AND (? IS NULL OR kind = ?) ORDER BY created_at, record_id", (shot_id, kind, kind))
        return [{**dict(r), "spec": json.loads(r["spec"]), "quality": json.loads(r["quality"]) if r["quality"] else None} for r in rows]

    def add_render(self, project_id: str, script_id: str, path: str, qc: dict) -> str:
        render_id = new_id("rnd")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO renders (render_id, project_id, script_id, path, qc, created_at) VALUES (?,?,?,?,?,?)",
                      (render_id, project_id, script_id, path, json.dumps(qc), time.time()))
        return render_id

    def set_render_review(self, render_id: str, *, approved: bool, comment: str | None = None) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE renders SET review = ? WHERE render_id = ?", (json.dumps({"approved": approved, "comment": comment, "at": time.time()}, ensure_ascii=False), render_id))

    def add_feedback(self, line: str, moment_id: str, verdict: str, *, asset_id: str | None = None) -> None:
        """What the operator made of a moment proposed for a line: "rejected" when they turned it down, "accepted" when they
        kept it. The latest word on a pair stands."""
        with db.write(self._conn) as c:
            c.execute("INSERT INTO match_feedback (line, moment_id, asset_id, verdict, at) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(line, moment_id) DO UPDATE SET verdict = excluded.verdict, at = excluded.at", (line.strip().lower(), moment_id, asset_id, verdict, time.time()))

    def feedback(self, line: str) -> dict[str, str]:
        """For one line: the verdict on each moment the operator has judged for it."""
        return {r["moment_id"]: r["verdict"] for r in self._conn.execute("SELECT moment_id, verdict FROM match_feedback WHERE line = ?", (line.strip().lower(),))}

    def feedback_counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self._conn.execute("SELECT verdict, COUNT(*) FROM match_feedback GROUP BY verdict")}

    def update_render_qc(self, render_id: str, **values) -> None:
        """Add to what is known about a render after it was made: a later look, a later measurement."""
        with db.write(self._conn) as c:
            qc = json.loads(c.execute("SELECT qc FROM renders WHERE render_id = ?", (render_id,)).fetchone()[0])
            c.execute("UPDATE renders SET qc = ? WHERE render_id = ?", (json.dumps({**qc, **values}, ensure_ascii=False), render_id))

    def renders(self, project_id: str, *, previews: bool = False) -> list[dict]:
        """The cuts of a project, newest first. Quick previews are another kind of thing and are listed only when asked for."""
        rows = self._conn.execute("SELECT * FROM renders WHERE project_id = ? ORDER BY created_at DESC, render_id DESC", (project_id,))
        out = [{**dict(r), "qc": json.loads(r["qc"]), "review": json.loads(r["review"]) if r["review"] else None} for r in rows]
        return [r for r in out if bool(r["qc"].get("preview")) == previews]

    def render(self, render_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM renders WHERE render_id = ?", (render_id,)).fetchone()
        return {**dict(row), "qc": json.loads(row["qc"]), "review": json.loads(row["review"]) if row["review"] else None} if row else None
