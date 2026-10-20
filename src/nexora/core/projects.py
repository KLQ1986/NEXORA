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
    illustration: dict = field(default_factory=dict)   # how the picture illustrates the words: mode (direct, associative, contrast), evokes, feel
    quote: dict | None = None         # a line someone says in the footage, played with its own sound: {asset_id, moment_id, t_in, t_out} ({} until found)


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

    def create_project(self, title: str, *, format: str = "landscape", production_id: str | None = None) -> str:
        """A video. It belongs to the production named, else to a new production of its own title (design 2026-10-18)."""
        project_id, now = new_id("prj"), time.time()
        with db.write(self._conn) as c:
            if not production_id or not c.execute("SELECT 1 FROM productions WHERE production_id = ?", (production_id,)).fetchone():
                production_id = new_id("prd")
                c.execute("INSERT INTO productions (production_id, title, created_at) VALUES (?,?,?)", (production_id, title, now))
            c.execute("INSERT INTO projects (project_id, title, format, created_at, production_id) VALUES (?,?,?,?,?)", (project_id, title, format, now, production_id))
        return project_id

    def update_project(self, project_id: str, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("title", "format", "music_path", "auto_accept", "style", "narration_dir", "budget_cap", "voice", "music_gain", "template", "profile", "research", "due_date", "bible", "options", "channel", "idea", "channel_version", "production_id")}
        with db.write(self._conn) as c:
            for key, value in allowed.items():
                c.execute(f"UPDATE projects SET {key} = ? WHERE project_id = ?", (value, project_id))

    def projects(self, *, include_trashed: bool = False) -> list[dict]:
        """The projects, newest first. What is in the Trash is left out unless asked for."""
        where = "" if include_trashed else " WHERE trashed_at IS NULL"
        return [dict(r) for r in self._conn.execute(f"SELECT * FROM projects{where} ORDER BY created_at DESC, project_id DESC")]

    def trash(self, project_id: str, *, at: float | None = None) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE projects SET trashed_at = ? WHERE project_id = ?", (at or time.time(), project_id))

    def restore(self, project_id: str) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE projects SET trashed_at = NULL WHERE project_id = ?", (project_id,))

    def trashed(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM projects WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC")]

    def project(self, project_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def save_script(self, project_id: str, lines: list, *, label: str | None = None) -> str:
        """A script is never edited in place: saving creates the next version. A line is its words, or a dict with its words
        (`text`) and the notes written with it (`brief`, `illustration`, `quote`), which take the place of any it carried before.
        A line starting with "> " is a quote: words someone says in the footage, played with their own sound; one that knows
        its stretch of the recording has that stretch as its clip at once, accepted, since the operator chose it."""
        script_id = new_id("scr")
        with db.write(self._conn) as c:
            version = c.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM scripts WHERE project_id = ?", (project_id,)).fetchone()[0]
            c.execute("INSERT INTO scripts (script_id, project_id, version, label, created_at) VALUES (?,?,?,?,?)", (script_id, project_id, version, label, time.time()))
            # A line starting with "#" names a scene; the lines after it belong to that scene. Notes a line carried in the
            # previous version follow it into the new one, as long as its words are unchanged.
            before = {r["text"]: r for r in c.execute("SELECT s.text, s.brief, s.screen_text, s.target_seconds, s.sound_cue, s.is_fact, s.source, s.fact_check, s.gen, s.illustration, s.quote "
                                                      "FROM shots s JOIN scripts sc USING (script_id) WHERE sc.project_id = ? AND sc.version = ?", (project_id, version - 1))}
            scene, position = None, 0
            for line in lines:
                given = line if isinstance(line, dict) else {"text": line}
                text = str(given.get("text") or "").strip()
                if not text:
                    continue
                if text.startswith("#"):
                    scene = text.lstrip("# ").strip() or None
                    continue
                quoted = text.startswith(">")
                if quoted:
                    text = text.lstrip("> ").strip()
                    if not text:
                        continue
                kept = before.get(text)
                notes = [kept["brief"], kept["screen_text"], kept["target_seconds"], kept["sound_cue"], kept["is_fact"], kept["source"], kept["fact_check"], kept["gen"], kept["illustration"], kept["quote"]] \
                    if kept else [None, None, None, None, 0, None, None, None, None, None]
                if given.get("brief"):
                    notes[0] = str(given["brief"]).strip()
                if given.get("illustration"):
                    notes[8] = json.dumps(given["illustration"], ensure_ascii=False)
                if given.get("screen_text"):
                    notes[1] = str(given["screen_text"]).strip()
                if given.get("is_fact"):
                    notes[4] = 1
                if given.get("source"):
                    notes[5] = str(given["source"]).strip()
                if isinstance(given.get("fact_check"), dict):
                    notes[6] = json.dumps(given["fact_check"], ensure_ascii=False)
                ref = given.get("quote") if isinstance(given.get("quote"), dict) else (json.loads(notes[9]) if notes[9] else {})
                ref = {k: ref[k] for k in ("asset_id", "moment_id", "t_in", "t_out") if ref.get(k) is not None} if ref else {}
                notes[9] = json.dumps(ref, ensure_ascii=False) if quoted else None       # a line no longer marked "> " is narration again
                shot_id = new_id("sht")
                c.execute("INSERT INTO shots (shot_id, script_id, position, text, scene, brief, screen_text, target_seconds, sound_cue, is_fact, source, fact_check, gen, illustration, quote) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (shot_id, script_id, position, text, scene, *notes))
                if quoted and ref.get("asset_id") and ref.get("t_out") is not None:
                    c.execute("INSERT INTO selections (shot_id, status, asset_id, moment_id, t_in, t_out, score, reason, alternates, decided_by, extras) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                              (shot_id, "accepted", ref["asset_id"], ref.get("moment_id"), float(ref["t_in"]), float(ref["t_out"]), None,
                               "Trích lời: đoạn người trong footage nói câu này, giữ nguyên tiếng.", "[]", "operator", json.dumps({"live_sound": True})))
                position += 1
        return script_id

    def keep_draft(self, project_id: str, lines: list) -> None:
        """What the writer said about each line of a draft it wrote (what to see, how to illustrate, what it states and on what source), kept until the draft is
        saved, so lines the operator keeps word for word bring their notes with them."""
        notes = {str(l["text"]).strip().lstrip("> ").strip(): {k: l[k] for k in ("brief", "illustration", "quote", "screen_text", "is_fact", "source", "fact_check") if l.get(k)} for l in lines if isinstance(l, dict) and l.get("text")}
        with db.write(self._conn) as c:
            c.execute("INSERT OR REPLACE INTO script_drafts (project_id, notes, at) VALUES (?,?,?)", (project_id, json.dumps(notes, ensure_ascii=False), time.time()))

    def drafted(self, project_id: str) -> dict[str, dict]:
        row = self._conn.execute("SELECT notes FROM script_drafts WHERE project_id = ?", (project_id,)).fetchone()
        return json.loads(row[0]) if row else {}

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
            if "quote" in more:                            # the stretch of a recording a quote is said in
                c.execute("UPDATE shots SET quote = ? WHERE shot_id = ?", (json.dumps(more["quote"] or {}, ensure_ascii=False), shot_id))
            if "illustration" in more:                     # how the picture illustrates the words, set as a whole
                value = more["illustration"] or None
                c.execute("UPDATE shots SET illustration = ? WHERE shot_id = ?", (json.dumps(value, ensure_ascii=False) if value else None, shot_id))
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
                c.execute("INSERT INTO shots (shot_id, script_id, position, text, scene, brief, screen_text, target_seconds, sound_cue, is_fact, source, fact_check, gen, illustration, quote) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (fresh, new_id_, position, text, old_shot.scene, old_shot.brief, old_shot.screen_text, old_shot.target_seconds, old_shot.sound_cue,
                           int(old_shot.is_fact and kept), old_shot.source if kept else None,
                           json.dumps(old_shot.fact_check, ensure_ascii=False) if old_shot.fact_check and kept else None, json.dumps(old_shot.gen, ensure_ascii=False) if old_shot.gen else None,
                           json.dumps(old_shot.illustration, ensure_ascii=False) if old_shot.illustration else None,
                           json.dumps(old_shot.quote if kept else {}, ensure_ascii=False) if old_shot.quote is not None else None))
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
        new = self.create_project(title, format=format, production_id=source.get("production_id"))     # beside the video it was made from
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
                      json.loads(r["fact_check"]) if r["fact_check"] else None, json.loads(r["gen"]) if r["gen"] else {},
                      json.loads(r["illustration"]) if r["illustration"] else {}, json.loads(r["quote"]) if r["quote"] is not None else None)
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
            "WHERE sel.asset_id IS NOT NULL AND sel.status != 'gap' AND sc.version = (SELECT MAX(version) FROM scripts WHERE project_id = sc.project_id) "
            "AND sc.project_id IN (SELECT project_id FROM projects WHERE trashed_at IS NULL)")
        out: dict[str, list[str]] = {}
        for asset_id, project_id in rows:
            out.setdefault(asset_id, []).append(project_id)
        return out

    def script_ids(self, project_id: str) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT script_id FROM scripts WHERE project_id = ? ORDER BY version", (project_id,))]

    def current_script(self, project_id: str) -> dict | None:
        row = self._conn.execute("SELECT script_id FROM scripts WHERE project_id = ? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
        return self.script(row[0]) if row else None

    # -------------------------------------------------------------------------------------- alternate openings and endings
    def add_variants(self, project_id: str, script_id: str, part: str, items: list[dict]) -> list[str]:
        """Alternatives for one part of a script, each kept whole: `items` are {label, note, lines}. Earlier alternatives of the
        same part of the same version are replaced unless one was chosen."""
        ids = []
        with db.write(self._conn) as c:
            c.execute("DELETE FROM script_variants WHERE project_id = ? AND script_id = ? AND part = ? AND chosen IS NULL", (project_id, script_id, part))
            for item in items:
                vid = new_id("var")
                c.execute("INSERT INTO script_variants (variant_id, project_id, script_id, part, label, note, lines, created_at) VALUES (?,?,?,?,?,?,?,?)",
                          (vid, project_id, script_id, part, item["label"], item.get("note") or None, json.dumps(item["lines"], ensure_ascii=False), time.time()))
                ids.append(vid)
        return ids

    def variants(self, project_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM script_variants WHERE project_id = ? ORDER BY created_at, label", (project_id,))
        return [{**dict(r), "lines": json.loads(r["lines"])} for r in rows]

    def choose_variant(self, variant_id: str) -> str:
        """The alternative becomes the script's next version, under its label; the others stay to choose later."""
        r = self._conn.execute("SELECT * FROM script_variants WHERE variant_id = ?", (variant_id,)).fetchone()
        if r is None:
            raise LookupError(variant_id)
        script_id = self.save_script(r["project_id"], json.loads(r["lines"]), label=r["label"])
        with db.write(self._conn) as c:
            c.execute("UPDATE script_variants SET chosen = ? WHERE variant_id = ?", (script_id, variant_id))
        return script_id

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

    def add_feedback(self, line: str, moment_id: str, verdict: str, *, asset_id: str | None = None, span: tuple[float, float] | None = None) -> None:
        """What the operator made of a moment proposed for a line: "rejected" when they turned it down, "accepted" when they
        kept it. The latest word on a pair stands. `span` is the stretch of footage the verdict was about, so that it still
        counts after the footage has been divided anew."""
        t_in, t_out = span or (None, None)
        with db.write(self._conn) as c:
            c.execute("INSERT INTO match_feedback (line, moment_id, asset_id, verdict, at, t_in, t_out) VALUES (?,?,?,?,?,?,?) "
                      "ON CONFLICT(line, moment_id) DO UPDATE SET verdict = excluded.verdict, at = excluded.at, t_in = COALESCE(excluded.t_in, t_in), t_out = COALESCE(excluded.t_out, t_out)",
                      (line.strip().lower(), moment_id, asset_id, verdict, time.time(), t_in, t_out))

    def forget_asset(self, asset_id: str, *, reason: str) -> int:
        """An asset has left the library. Every line that showed it is without a picture again and says why; it is no longer
        offered as an alternate or cut to in the middle of a line; and what was said about its clips is dropped. Returns how
        many lines lost their picture."""
        gaps = 0
        with db.write(self._conn) as c:
            for row in c.execute("SELECT shot_id, asset_id, alternates, extras FROM selections").fetchall():
                alternates, extras = json.loads(row["alternates"] or "[]"), json.loads(row["extras"] or "{}")
                kept = [a for a in alternates if a.get("asset_id") != asset_id]
                cleaned = dict(extras)
                if "inserts" in cleaned:
                    cleaned["inserts"] = [i for i in cleaned["inserts"] if i.get("asset_id") != asset_id]
                for key in ("pending_asset", "sfx"):
                    if cleaned.get(key) == asset_id:
                        cleaned[key] = None
                if isinstance(cleaned.get("focus"), dict) and cleaned["focus"].get("asset_id") == asset_id:
                    cleaned["focus"] = None
                held = (cleaned.get("trashed_pick") or {}).get("asset_id") == asset_id
                if held:
                    cleaned.pop("trashed_pick")           # it was waiting in the Trash and is not coming back
                if row["asset_id"] == asset_id or held:
                    gaps += 1
                    c.execute("UPDATE selections SET status = 'gap', asset_id = NULL, moment_id = NULL, t_in = NULL, t_out = NULL, score = NULL, reason = ?, "
                              "alternates = ?, extras = ?, decided_by = 'system' WHERE shot_id = ?",
                              (reason, json.dumps(kept, ensure_ascii=False), json.dumps(cleaned, ensure_ascii=False), row["shot_id"]))
                elif kept != alternates or cleaned != extras:
                    c.execute("UPDATE selections SET alternates = ?, extras = ? WHERE shot_id = ?",
                              (json.dumps(kept, ensure_ascii=False), json.dumps(cleaned, ensure_ascii=False), row["shot_id"]))
            c.execute("DELETE FROM match_feedback WHERE asset_id = ?", (asset_id,))
        return gaps

    def remove(self, project_id: str) -> dict:
        """Delete a project with every version of its script, its lines, what was chosen and generated for them, and the
        records of its cuts. The cut files are not touched here; their paths are returned so the caller decides what to do
        with them. What the operator said about clips stays, since it is about the footage, not about this project."""
        with db.write(self._conn) as c:
            scripts = [r[0] for r in c.execute("SELECT script_id FROM scripts WHERE project_id = ?", (project_id,))]
            marks = ",".join("?" * len(scripts))
            shots = [r[0] for r in c.execute(f"SELECT shot_id FROM shots WHERE script_id IN ({marks})", scripts)] if scripts else []
            renders = [dict(r) for r in c.execute("SELECT render_id, path FROM renders WHERE project_id = ?", (project_id,))]
            for i in range(0, len(shots), 500):
                part = shots[i:i + 500]
                held = ",".join("?" * len(part))
                c.execute(f"DELETE FROM selections WHERE shot_id IN ({held})", part)
                c.execute(f"DELETE FROM generations WHERE shot_id IN ({held})", part)
                c.execute(f"DELETE FROM shots WHERE shot_id IN ({held})", part)
            if scripts:
                c.execute(f"DELETE FROM scripts WHERE script_id IN ({marks})", scripts)
            c.execute("DELETE FROM renders WHERE project_id = ?", (project_id,))
            c.execute("DELETE FROM script_variants WHERE project_id = ?", (project_id,))
            c.execute("DELETE FROM script_drafts WHERE project_id = ?", (project_id,))
            c.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
        return {"scripts": scripts, "shots": shots, "renders": renders}

    def set_aside_asset(self, asset_id: str, *, reason: str) -> int:
        """An asset has gone to the Trash. Every line showing it is without a picture again and says why; what it showed is
        kept with the line, so that bringing the asset back can give the line its picture again. Returns how many lines."""
        moved = 0
        with db.write(self._conn) as c:
            for row in c.execute("SELECT * FROM selections WHERE asset_id = ? AND status != 'gap'", (asset_id,)).fetchall():
                extras = json.loads(row["extras"] or "{}")
                extras["trashed_pick"] = {k: row[k] for k in ("status", "asset_id", "moment_id", "t_in", "t_out", "score", "reason", "decided_by")}
                c.execute("UPDATE selections SET status = 'gap', asset_id = NULL, moment_id = NULL, t_in = NULL, t_out = NULL, score = NULL, reason = ?, "
                          "extras = ?, decided_by = 'system' WHERE shot_id = ?", (reason, json.dumps(extras, ensure_ascii=False), row["shot_id"]))
                moved += 1
        return moved

    def bring_back_asset(self, asset_id: str) -> int:
        """An asset has come back from the Trash. Each line it was taken from gets it back, unless the line has been given
        another picture since. Returns how many lines got it back."""
        back = 0
        with db.write(self._conn) as c:
            for row in c.execute("SELECT shot_id, status, extras FROM selections WHERE extras LIKE ?", (f"%{asset_id}%",)).fetchall():
                extras = json.loads(row["extras"] or "{}")
                pick = extras.get("trashed_pick")
                if not pick or pick.get("asset_id") != asset_id:
                    continue
                extras.pop("trashed_pick")
                if row["status"] == "gap":
                    c.execute("UPDATE selections SET status = ?, asset_id = ?, moment_id = ?, t_in = ?, t_out = ?, score = ?, reason = ?, decided_by = ?, extras = ? "
                              "WHERE shot_id = ?", (pick["status"], pick["asset_id"], pick["moment_id"], pick["t_in"], pick["t_out"], pick["score"], pick["reason"],
                                                    pick["decided_by"], json.dumps(extras, ensure_ascii=False), row["shot_id"]))
                    back += 1
                else:
                    c.execute("UPDATE selections SET extras = ? WHERE shot_id = ?", (json.dumps(extras, ensure_ascii=False), row["shot_id"]))
        return back

    def feedback_spans(self, line: str) -> list[dict]:
        """For one line: each stretch of footage the operator has judged for it, latest first."""
        rows = self._conn.execute("SELECT asset_id, t_in, t_out, verdict FROM match_feedback WHERE line = ? AND asset_id IS NOT NULL AND t_in IS NOT NULL ORDER BY at DESC",
                                  (line.strip().lower(),))
        return [dict(r) for r in rows]

    def feedback(self, line: str) -> dict[str, str]:
        """For one line: the verdict on each moment the operator has judged for it."""
        return {r["moment_id"]: r["verdict"] for r in self._conn.execute("SELECT moment_id, verdict FROM match_feedback WHERE line = ?", (line.strip().lower(),))}

    def feedback_counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self._conn.execute("SELECT verdict, COUNT(*) FROM match_feedback GROUP BY verdict")}

    def remove_render(self, render_id: str) -> dict | None:
        """Forget one cut. Returns its record, so that the caller decides what to do with its file."""
        render = self.render(render_id)
        if render is not None:
            with db.write(self._conn) as c:
                c.execute("DELETE FROM renders WHERE render_id = ?", (render_id,))
        return render

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
