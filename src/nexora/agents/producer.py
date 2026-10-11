"""The producer: an agent that takes a goal and carries a video through the pipeline, one decision at a time.

It sits above the domain modules and uses only what the operator could do through them: write a script, start a match,
fill a gap, start a render. Each role speaks in the task's log, so every decision can be read afterwards. It never
passes a human gate on its own: at a review it stops and waits.

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
MAX_STOCK_FILLS = 3
SCHEMA = """CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, goal TEXT NOT NULL, status TEXT NOT NULL, step TEXT NOT NULL,
    options TEXT NOT NULL, log TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL, updated_at REAL NOT NULL)"""


class Producer:
    def __init__(self, db_path, *, orch, projects, planning, sourcing, edit, adapters, fill_gap):
        self._db = db.LocalConnections(db_path)
        self._orch, self._projects, self._planning, self._sourcing, self._edit, self._adapters = orch, projects, planning, sourcing, edit, adapters
        self._fill_gap = fill_gap                    # (shot_id, query) -> {"found": bool, ...}; given by the composition root
        with db.write(self._conn) as c:
            c.execute(SCHEMA)

    @property
    def _conn(self):
        return self._db.get()

    # ------------------------------------------------------------------ tasks
    def start(self, goal: str, *, title: str | None = None, format: str = "landscape", lines: int = 5, use_stock: bool = True) -> str:
        project_id = self._planning.create_project(title or goal[:60], format=format)
        task_id, now = new_id("tsk"), time.time()
        with db.write(self._conn) as c:
            c.execute("INSERT INTO agent_tasks (task_id, project_id, goal, status, step, options, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                      (task_id, project_id, goal, "working", "write", json.dumps({"lines": lines, "use_stock": use_stock}), now, now))
        self._say(task_id, LEAD, f"Nhận việc: {goal}")
        return task_id

    def task(self, task_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return {**dict(row), "options": json.loads(row["options"]), "log": json.loads(row["log"])} if row else None

    def tasks(self, *, project_id: str | None = None) -> list[dict]:
        rows = self._conn.execute("SELECT task_id FROM agent_tasks WHERE (? IS NULL OR project_id = ?) ORDER BY created_at DESC", (project_id, project_id))
        return [self.task(r[0]) for r in rows]

    def _say(self, task_id: str, role: str, text: str) -> None:
        with db.write(self._conn) as c:
            log = json.loads(c.execute("SELECT log FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()[0])
            log.append({"at": time.time(), "role": role, "text": text})
            c.execute("UPDATE agent_tasks SET log = ?, updated_at = ? WHERE task_id = ?", (json.dumps(log, ensure_ascii=False), time.time(), task_id))

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
        for row in self._conn.execute("SELECT task_id FROM agent_tasks WHERE status IN ('working', 'waiting_operator')").fetchall():
            try:
                moved += bool(self.advance(row[0]))
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

        if step == "write":
            lines = self._planning.draft_script(task["goal"], lines=task["options"]["lines"])
            if not lines:
                self._say(task_id, WRITER, "Không viết được kịch bản từ kho footage hiện có.")
                self._move(task_id, status="failed")
                return True
            self._planning.save_script(project_id, lines)
            self._say(task_id, WRITER, f"Viết {len(lines)} câu, chỉ dùng những gì kho footage đang có.")
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
            gaps = [s for s in self._projects.selections(script["script_id"]) if s.status == "gap"]
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
                self._say(task_id, LEAD, "Chờ bạn xem và duyệt các clip đã chọn.")
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
