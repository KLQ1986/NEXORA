"""The producer: an agent that takes a goal and carries a video through the pipeline, one decision at a time.

It sits above the domain modules and uses only what the operator could do through them: write a script, start a match,
fill a gap, start a render. Each role speaks in the task's log, so every decision can be read afterwards. It never
passes a human gate on its own: at a review it stops and waits.

The roles are bounded: the critic is heard once and the writer answers once, the researcher reads only the pages the
operator named, and a task that has taken more steps than any real one needs is stopped rather than left to wander.

It is a state machine advanced by `tick()`, never a long-running call, so it survives restarts and holds no worker.
"""
import json
import time

from nexora.core import db
from nexora.core.adapter import AdapterError, Request
from nexora.core.ids import new_id
from nexora.core.states import RunStatus

QUERY_PROMPT = (
    "Câu lời dẫn của một video: \"{line}\".\nViết một cụm từ khoá tiếng Anh từ 2 đến 5 từ để tìm video stock minh hoạ câu này. "
    "Chỉ trả về JSON với khoá tu_khoa."
)
WRITER, SCOUT, STOCK, EDITOR, LEAD = "Biên kịch", "Tìm hình", "Tìm stock", "Dựng phim", "Điều phối"
RESEARCHER, CRITIC, CHECKER = "Nghiên cứu", "Phản biện", "Kiểm chứng"
MAX_STOCK_FILLS = 3
MAX_REVISIONS = 1            # the writer answers the critic once; a second round rarely pays for itself
MAX_SOURCES = 5
MAX_STEPS = 40               # no task needs this many moves; one that reaches it is going round in circles
SCHEMA = """CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, goal TEXT NOT NULL, status TEXT NOT NULL, step TEXT NOT NULL,
    options TEXT NOT NULL, log TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL, updated_at REAL NOT NULL)"""


def short_title(text: str, limit: int = 60) -> str:
    """A title no longer than `limit`, cut between words, never inside one: the title is read back by the critic and the
    writer as the topic, so a word cut in half ends up in the script."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit + 1].rsplit(" ", 1)[0] if " " in text[:limit + 1] else text[:limit]
    return cut.rstrip(" ,;:.-–—")


class Producer:
    def __init__(self, db_path, *, orch, projects, planning, sourcing, edit, adapters, fill_gap, to_storyboard=None, style=None):
        self._db = db.LocalConnections(db_path)
        self._orch, self._projects, self._planning, self._sourcing, self._edit, self._adapters = orch, projects, planning, sourcing, edit, adapters
        self._fill_gap = fill_gap                    # (shot_id, query) -> {"found": bool, ...}; given by the composition root
        self._style = style or (lambda project_id: "mixed")     # (project_id) -> how its pictures illustrate the words
        self._to_storyboard = to_storyboard          # (project_id) -> None: the chosen clips laid out on the storyboard, where they are approved
        with db.write(self._conn) as c:
            c.execute(SCHEMA)

    @property
    def _conn(self):
        return self._db.get()

    # ------------------------------------------------------------------ tasks
    def start(self, goal: str, *, title: str | None = None, format: str = "landscape", lines: int = 5, use_stock: bool = True,
              urls: list[str] | None = None, critique: bool = True, find_sources: bool = False, production_id: str | None = None) -> str:
        project_id = self._planning.create_project(short_title(title or goal), format=format, production_id=production_id)
        task_id, now = new_id("tsk"), time.time()
        with db.write(self._conn) as c:
            c.execute("INSERT INTO agent_tasks (task_id, project_id, goal, status, step, options, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                      (task_id, project_id, goal, "working", "research" if urls or find_sources else "write",
                       json.dumps({"lines": lines, "use_stock": use_stock, "urls": list(urls or [])[:MAX_SOURCES], "critique": critique, "find_sources": find_sources, "steps": 0, "revisions": 0}), now, now))
        self._say(task_id, LEAD, f"Nhận việc: {goal}")
        return task_id

    def task(self, task_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return {**dict(row), "options": json.loads(row["options"]), "log": json.loads(row["log"])} if row else None

    def tasks(self, *, project_id: str | None = None) -> list[dict]:
        rows = self._conn.execute("SELECT task_id FROM agent_tasks WHERE (? IS NULL OR project_id = ?) ORDER BY created_at DESC", (project_id, project_id))
        return [self.task(r[0]) for r in rows]

    def forget_project(self, project_id: str) -> int:
        """A project has been deleted: what the producer did for it goes with it. Returns how many tasks were dropped."""
        with db.write(self._conn) as c:
            return c.execute("DELETE FROM agent_tasks WHERE project_id = ?", (project_id,)).rowcount

    def pause(self, task_id: str) -> bool:
        """The task takes no further step until it is resumed; a stage already running finishes. Its state comes back on resume."""
        task = self.task(task_id)
        if task is None or task["status"] not in ("working", "waiting_operator"):
            return False
        with db.write(self._conn) as c:
            c.execute("UPDATE agent_tasks SET status = 'paused', options = ? WHERE task_id = ?", (json.dumps({**task["options"], "before_pause": task["status"]}), task_id))
        self._say(task_id, LEAD, "Tạm dừng theo lệnh của bạn.")
        return True

    def resume(self, task_id: str) -> bool:
        task = self.task(task_id)
        if task is None or task["status"] != "paused":
            return False
        self._move(task_id, status=task["options"].get("before_pause") or "working")
        self._say(task_id, LEAD, "Tiếp tục.")
        return True

    def retry(self, task_id: str) -> bool:
        """A task stopped by a failure takes up again from the step it stopped at (its checkpoint), not from the start."""
        task = self.task(task_id)
        if task is None or task["status"] != "failed":
            return False
        self._move(task_id, status="working")
        self._say(task_id, LEAD, f"Chạy lại từ bước “{task['step']}”.")
        return True

    def cancel(self, task_id: str) -> bool:
        task = self.task(task_id)
        if task is None or task["status"] in ("done", "failed", "cancelled"):
            return False
        self._move(task_id, status="cancelled")
        self._say(task_id, LEAD, "Đã huỷ theo lệnh của bạn.")
        return True

    def _say(self, task_id: str, role: str, text: str) -> None:
        with db.write(self._conn) as c:
            log = json.loads(c.execute("SELECT log FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()[0])
            log.append({"at": time.time(), "role": role, "text": text})
            c.execute("UPDATE agent_tasks SET log = ?, updated_at = ? WHERE task_id = ?", (json.dumps(log, ensure_ascii=False), time.time(), task_id))

    def _count(self, task_id: str, key: str) -> int:
        with db.write(self._conn) as c:
            options = json.loads(c.execute("SELECT options FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()[0])
            options[key] = options.get(key, 0) + 1
            c.execute("UPDATE agent_tasks SET options = ? WHERE task_id = ?", (json.dumps(options), task_id))
        return options[key]

    def _move(self, task_id: str, *, step: str | None = None, status: str | None = None) -> None:
        with db.write(self._conn) as c:
            if step:
                c.execute("UPDATE agent_tasks SET step = ? WHERE task_id = ?", (step, task_id))
            if status:
                c.execute("UPDATE agent_tasks SET status = ? WHERE task_id = ?", (status, task_id))

    # ------------------------------------------------------------------ the loop
    def tick(self) -> int:
        """Give every unfinished task one chance to move. Returns how many moved."""
        moved = 0
        for row in self._conn.execute("SELECT task_id FROM agent_tasks WHERE status IN ('working', 'waiting_operator') "
                                      "AND project_id NOT IN (SELECT project_id FROM projects WHERE trashed_at IS NOT NULL)").fetchall():      # a project in the Trash waits
            try:
                if self.advance(row[0]):
                    moved += 1
                    if self._count(row[0], "steps") > MAX_STEPS and self.task(row[0])["status"] == "working":
                        self._say(row[0], LEAD, f"Dừng lại: việc này đã đi quá {MAX_STEPS} bước mà chưa xong.")
                        self._move(row[0], status="failed")
            except AdapterError as err:
                self._say(row[0], LEAD, f"Dừng lại vì công cụ báo lỗi: {err.message or err.code.value}")
                self._move(row[0], status="failed")
        return moved

    def _latest(self, script_id: str, pipeline: str) -> str | None:
        return next((r for r in self._orch.runs_for_subject(script_id) if self._orch.pipeline_of(r) == pipeline), None)

    def advance(self, task_id: str) -> bool:
        """Take the next step if there is one to take now. Returns False when the task is waiting on something else."""
        task = self.task(task_id)
        step, project_id = task["step"], task["project_id"]
        script = self._projects.current_script(project_id)

        if step == "research":
            read = 0
            for url in task["options"].get("urls", []):
                try:
                    source = self._planning.read_source(project_id, url)
                    self._say(task_id, RESEARCHER, f"Đã đọc “{source['title']}” ({source['publisher']}).")
                    read += 1
                except AdapterError as err:
                    self._say(task_id, RESEARCHER, f"Không đọc được {url}: {err.message or err.code.value}")
            if task["options"].get("find_sources") and read < MAX_SOURCES:
                try:
                    found = self._planning.find_sources(project_id, task["goal"], limit=min(3, MAX_SOURCES - read))
                    for source in found:
                        self._say(task_id, RESEARCHER, f"Tự tìm và đọc “{source['title']}” ({source['publisher']}).")
                    read += len(found)
                except AdapterError as err:
                    self._say(task_id, RESEARCHER, f"Không tự tìm được nguồn: {err.message or err.code.value}")
            self._say(task_id, RESEARCHER, f"Có {read} nguồn để đối chiếu dữ kiện.")
            self._move(task_id, step="write")
            return True

        if step == "write":
            lines = self._planning.draft(task["goal"], lines=task["options"]["lines"], style=self._style(project_id))
            if not lines:
                self._say(task_id, WRITER, "Không viết được kịch bản từ kho footage hiện có.")
                self._move(task_id, status="failed")
                return True
            self._planning.save_script(project_id, lines)
            said = [l for l in lines if isinstance(l, dict)]
            ways = {m: sum(1 for l in said if (l.get("illustration") or {}).get("mode") == m) for m in ("direct", "associative", "contrast")}
            self._say(task_id, WRITER, f"Viết {len(said)} câu, chỉ dùng những gì kho footage đang có"
                      + (f": {ways['direct']} câu minh hoạ trực tiếp, {ways['associative']} câu liên tưởng" + (f", {ways['contrast']} câu tương phản" if ways["contrast"] else "") + "." if any(ways.values()) else "."))
            self._move(task_id, step="critique" if task["options"].get("critique", True) else "facts")
            return True

        if step == "critique":
            notes = self._planning.critique(project_id)
            if not notes:
                self._say(task_id, CRITIC, "Không có điểm nào cần sửa.")
            else:
                self._say(task_id, CRITIC, f"Nêu {len(notes)} điểm: " + " ".join(f"({i}) {n['issue']}" for i, n in enumerate(notes, 1)))
                if task["options"].get("revisions", 0) < MAX_REVISIONS:
                    self._count(task_id, "revisions")
                    revised = self._planning.revise(project_id)
                    self._say(task_id, WRITER, "Đã viết lại theo nhận xét, thành phiên bản kịch bản mới." if revised else "Giữ nguyên kịch bản: bản viết lại không khác bản cũ.")
            self._move(task_id, step="facts")
            return True

        if step == "facts":
            facts = self._planning.find_facts(project_id)
            if facts:
                results = self._planning.check_facts(project_id)
                good = sum(r["verdict"] == "supported" for r in results)
                wrong = [r for r in results if r["verdict"] == "contradicted"]
                self._say(task_id, CHECKER, f"{len(results)} câu nêu dữ kiện: {good} câu có nguồn xác nhận, {len(wrong)} câu trái với nguồn, {len(results) - good - len(wrong)} câu chưa có nguồn nào nhắc tới."
                                            + "".join(f" Trái nguồn: “{r['text']}”." for r in wrong))
            else:
                self._say(task_id, CHECKER, "Kịch bản không có câu nào nêu dữ kiện cần kiểm chứng.")
            self._move(task_id, step="source")
            return True

        if step == "source":
            self._sourcing.start_match(script["script_id"])
            self._say(task_id, SCOUT, "Bắt đầu tìm clip cho từng câu.")
            self._move(task_id, step="matching")
            return True

        if step == "matching":
            status = self._orch.run_status(self._latest(script["script_id"], "sourcing.match"))
            if status in (RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.CANCELLED):
                self._say(task_id, SCOUT, "Việc tìm clip không chạy được. Xem ở mục Tiến trình.")
                self._move(task_id, status="failed")
                return True
            if status not in (RunStatus.WAITING_REVIEW, RunStatus.SUCCEEDED):
                return False
            sels = self._projects.selections(script["script_id"])
            gaps = [s for s in sels if s.status == "gap"]
            self._say(task_id, SCOUT, f"Có clip cho {len(sels) - len(gaps)} trên {len(sels)} câu." + (f" Còn {len(gaps)} câu thiếu hình." if gaps else ""))
            self._move(task_id, step="gaps")
            return True

        if step == "gaps":
            texts = {s.shot_id: s.text for s in script["shots"]}
            quotes = {s.shot_id for s in script["shots"] if s.quote is not None}         # someone's own words are never filled with stock
            gaps = [s for s in self._projects.selections(script["script_id"]) if s.status == "gap" and s.shot_id not in quotes]
            has_stock = any(c.name == "stock" for c in self._adapters.describe())
            for sel in gaps[:MAX_STOCK_FILLS] if task["options"]["use_stock"] and has_stock else []:
                query = ""
                try:
                    out = self._adapters.submit("model", Request("chat", params={"prompt": QUERY_PROMPT.format(line=texts[sel.shot_id]), "json": True, "max_tokens": 40}))
                    query = str(out.outputs["json"].get("tu_khoa", "")).strip()
                    found = bool(query) and self._fill_gap(sel.shot_id, query).get("found")
                except AdapterError:
                    found = False
                self._say(task_id, STOCK, f"Câu “{texts[sel.shot_id]}”: " + (f"lấy clip stock theo từ khoá “{query}”." if found else "không tìm được clip stock phù hợp."))
            self._move(task_id, step="review")
            return True

        if step == "review":
            if script["match_approved"]:
                self._say(task_id, LEAD, "Các clip đã được duyệt.")
                self._move(task_id, step="cut", status="working")
                return True
            if task["status"] != "waiting_operator":
                if self._to_storyboard is not None:
                    try:
                        self._to_storyboard(project_id)
                    except AdapterError as err:                 # the review still waits; only the layout is missing
                        self._say(task_id, LEAD, f"Không bày được clip lên Storyboard: {err.message or err.code.value}")
                self._say(task_id, LEAD, "Chờ bạn xem và duyệt các clip đã chọn trong Storyboard.")
                self._move(task_id, status="waiting_operator")
                return True
            return False

        if step == "cut":
            self._edit.start_render(script["script_id"])
            self._say(task_id, EDITOR, "Bắt đầu dựng video: lời dẫn, phụ đề, ghép cảnh.")
            self._move(task_id, step="cutting")
            return True

        if step == "cutting":
            status = self._orch.run_status(self._latest(script["script_id"], "edit.render"))
            if status in (RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.CANCELLED):
                self._say(task_id, EDITOR, "Việc dựng không chạy được. Xem ở mục Tiến trình.")
                self._move(task_id, status="failed")
                return True
            if status is RunStatus.WAITING_REVIEW and task["status"] != "waiting_operator":
                qc = self._projects.renders(project_id)[0]["qc"]
                self._say(task_id, EDITOR, f"Dựng xong bản dài {qc['duration']:.0f} giây. Kiểm tra tự động {'đạt' if qc['passed'] else 'chưa đạt'}"
                                           + (f", có {len(qc.get('findings', []))} điểm nên xem lại." if qc.get("findings") else "."))
                self._say(task_id, LEAD, "Chờ bạn xem và duyệt bản dựng.")
                self._move(task_id, status="waiting_operator")
                return True
            if status is RunStatus.SUCCEEDED:
                self._say(task_id, LEAD, "Bản dựng đã được duyệt. Xong việc.")
                self._move(task_id, status="done")
                return True
            return False
        return False
