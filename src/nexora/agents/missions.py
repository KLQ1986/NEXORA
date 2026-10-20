"""Mission Control's missions (design 2026-10-18): the operator's words made into a plan, the plan checked, and once confirmed
carried out through what NEXORA already has (the Producer for videos, the library's pipelines for footage).

The model only proposes the plan, and only from the catalogue below; whether the machine can do it, whether the budget allows
it and whether a paid service may be used are checked here, in code. A mission's status is read from the work it started:
nothing about the work is kept twice.
"""
from __future__ import annotations

from typing import Callable

from nexora.agents.producer import short_title
from nexora.core.adapter import AdapterError, PrivacyClass, Request
from nexora.core.missions import MissionStore
from nexora.core.schedule import in_window
from nexora.modules.planning.topic import DEFAULT_FORM, FORMS, clamp_seconds

KINDS = {
    "video": {"name": "Làm video từ kho footage", "pipelines": ("sourcing.match", "edit.render")},
    "understand": {"name": "Mô tả footage chưa được hiểu", "pipelines": ("library.understand",)},
    "transcribe": {"name": "Nghe lời nói trong footage chưa được nghe", "pipelines": ("library.transcribe",)},
    # A subject the library does not hold: Claude Code looks it up on the web and writes the script; the rest is a video's way.
    "topic": {"name": "Làm video theo chủ đề", "pipelines": ("planning.topic_script", "sourcing.match", "edit.render")},
}
MAKES_VIDEOS = ("video", "topic")
FORMATS = ("landscape", "portrait", "square")
MAX_VIDEOS = 10

PLAN_PROMPT = (
    "Bạn lập kế hoạch cho hệ thống làm video NEXORA. Người vận hành giao việc: \"{text}\".\n"
    "Chỉ được chọn một loại việc NEXORA làm được: video (làm một hay nhiều video từ kho footage), topic (làm video theo một chủ đề, sự kiện hay câu chuyện "
    "nằm ngoài kho footage: máy tự tìm nguồn trên web và viết kịch bản, hình lấy từ stock hoặc AI tạo), understand (mô tả footage chưa được hiểu), "
    "transcribe (nghe lời nói trong footage chưa được nghe).\n"
    "Các kênh: {channels}. Các mẫu video: {templates}.\n"
    "Trả về JSON với các khoá: loai (video | topic | understand | transcribe), muc_tieu (một câu nói video hay việc này nhằm điều gì), "
    "tieu_de (tên video ngắn, dưới 8 chữ, viết như câu thường, không có chữ \"video\"), so_video (số video, 1 nếu không nói), "
    "dinh_dang (landscape | portrait | square; video dọc là portrait), so_cau (số câu lời dẫn mỗi video, 5 nếu không nói), "
    "thoi_luong_phut (với topic: số phút lời dẫn mỗi video, 3 nếu không nói), "
    "the_loai (với topic: reportage là phóng sự, science là diễn giải khoa học, history là tài liệu lịch sử, story là chân dung hay kể chuyện, "
    "analysis là phân tích bình luận, news là điểm tin, howto là hướng dẫn; reportage nếu không rõ), kenh (tên một kênh ở trên hoặc chuỗi rỗng), "
    "mau (tên một mẫu ở trên hoặc chuỗi rỗng), ngan_sach_usd (số, hoặc null nếu không nói), dung_dich_vu_tra_tien (true chỉ khi người vận hành cho phép), "
    "tim_stock (true nếu được lấy video stock miễn phí cho câu thiếu hình), tu_phan_bien (true cho video, false cho topic), "
    "rang_buoc (danh sách ngắn các ràng buộc người vận hành nêu: thời lượng, phong cách...), nghiem_thu (danh sách ngắn: thế nào là xong và đạt)."
)

# The business status read from the children, in order of what the operator most needs to know.
CHILD = {"working": "running", "waiting_operator": "waiting", "done": "done", "failed": "failed", "cancelled": "cancelled", "paused": "paused",
         "queued": "queued", "running": "running", "waiting_review": "waiting", "blocked": "blocked", "succeeded": "done"}


def _flag(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip():
        return value.strip().lower() in ("true", "1", "co", "có", "yes")
    return default


def _int(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(float(value))))
    except (TypeError, ValueError):
        return default


def _seconds(raw: dict) -> int:
    """How long a video on a topic reads, from the plan's seconds or the minutes the model or the operator said."""
    if raw.get("seconds") is not None:
        return clamp_seconds(raw["seconds"])
    try:
        return clamp_seconds(float(raw.get("minutes")) * 60)
    except (TypeError, ValueError):
        return clamp_seconds(None)


def _texts(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in value or [] if str(v).strip()][:8]


class Missions:
    def __init__(self, store: MissionStore, *, orch, producer, projects, adapters, available: Callable[[str], list[str] | None],
                 channels: Callable[[], list[str]], templates: Callable[[], list[str]], budget_left: Callable[[], float | None],
                 prepare: Callable[[str, dict], None], start_library: Callable[[str], list[str]], autonomy: Callable[[], int],
                 new_production: Callable[[str], str] | None = None):
        self.store = store
        self._orch, self._producer, self._projects, self._adapters = orch, producer, projects, adapters
        self._available, self._channels, self._templates, self._budget_left = available, channels, templates, budget_left
        self._prepare, self._start_library, self._autonomy = prepare, start_library, autonomy
        self._new_production = new_production or (lambda title: None)

    # ------------------------------------------------------------------------------------------------------ the plan
    def _ask(self, text: str) -> dict:
        prompt = PLAN_PROMPT.format(text=text, channels=", ".join(self._channels()) or "(không có)", templates=", ".join(self._templates()) or "(không có)")
        out = self._adapters.submit("model", Request("chat", privacy_class=PrivacyClass.CLOUD_ALLOWED,
                                                     params={"task": "mission_plan", "prompt": prompt, "json": True, "max_tokens": 600})).outputs["json"]
        return self.normalise({"kind": out.get("loai"), "goal": out.get("muc_tieu") or text, "title": out.get("tieu_de"), "count": out.get("so_video"), "format": out.get("dinh_dang"),
                               "lines": out.get("so_cau"), "minutes": out.get("thoi_luong_phut"), "form": out.get("the_loai"), "channel": out.get("kenh"), "template": out.get("mau"), "budget": out.get("ngan_sach_usd"),
                               "paid": out.get("dung_dich_vu_tra_tien"), "stock": out.get("tim_stock"), "critique": out.get("tu_phan_bien"),
                               "constraints": out.get("rang_buoc"), "acceptance": out.get("nghiem_thu")})

    def normalise(self, raw: dict) -> dict:
        """A plan in the one shape the rest of the code reads, whoever wrote it (the model or the operator's edit)."""
        kind = str(raw.get("kind") or "").strip().lower()
        try:
            budget = None if raw.get("budget") in (None, "") else max(0.0, round(float(raw["budget"]), 2))
        except (TypeError, ValueError):
            budget = None
        fmt = str(raw.get("format") or "").strip().lower()
        goal = str(raw.get("goal") or "").strip()
        return {"kind": kind, "goal": goal, "title": short_title(raw.get("title") or goal), "count": _int(raw.get("count"), 1, 1, MAX_VIDEOS),
                "format": fmt if fmt in FORMATS else "landscape", "lines": _int(raw.get("lines"), 5, 2, 12),
                # A video on a topic is asked for by how long it reads and the kind of video it is, not by its lines.
                "seconds": _seconds(raw),
                "form": str(raw.get("form") or "").strip().lower() if str(raw.get("form") or "").strip().lower() in FORMS else DEFAULT_FORM,
                "channel": str(raw.get("channel") or "").strip() or None, "template": str(raw.get("template") or "").strip() or None,
                "budget": budget, "paid": _flag(raw.get("paid"), False), "stock": _flag(raw.get("stock"), True),
                "critique": _flag(raw.get("critique"), kind != "topic"),         # a writer that sourced its own lines has already gone over them
                "constraints": _texts(raw.get("constraints")), "acceptance": _texts(raw.get("acceptance")), "autonomy": self._autonomy(),
                "production_id": str(raw.get("production_id") or "").strip() or None}

    def check(self, plan: dict) -> list[str]:
        """What stops the plan from running, said plainly; an empty list when it can be confirmed."""
        problems = []
        kind = KINDS.get(plan["kind"])
        if kind is None:
            return [f"NEXORA chưa làm được loại việc này. Các loại làm được: {', '.join(k['name'] for k in KINDS.values())}."]
        missing = sorted({m for p in kind["pipelines"] for m in (self._available(p) or [])})
        if missing:
            problems.append(f"Máy này chưa chạy được “{kind['name']}”: thiếu {', '.join(missing)}.")
        if plan["kind"] in MAKES_VIDEOS:
            if not plan["goal"]:
                problems.append("Cần nói video nói về điều gì.")
            if plan["channel"] and plan["channel"] not in self._channels():
                problems.append(f"Không có kênh “{plan['channel']}”.")
            if plan["template"] and plan["template"] not in self._templates():
                problems.append(f"Không có mẫu “{plan['template']}”.")
        if plan["paid"] and plan["budget"] is None:
            problems.append("Việc được dùng dịch vụ trả tiền cần một ngân sách tối đa.")
        left = self._budget_left()
        if plan["budget"] and left is not None and plan["budget"] > left:
            problems.append(f"Ngân sách {plan['budget']:.2f} USD vượt phần còn lại của hạn mức hôm nay và tháng này ({left:.2f} USD).")
        return problems

    def plan(self, text: str, *, production_id: str | None = None, chosen: dict | None = None) -> dict:
        """A mission from the operator's words: planned when nothing stops it, else a draft that says what does. Given from a
        production, its videos go into it. What the operator chose as they asked (the kind of work, a topic video's kind and
        length) is taken over what the model read in their words."""
        text = text.strip()
        chosen = {k: v for k, v in (chosen or {}).items() if k in ("kind", "form", "seconds") and v not in (None, "")}
        try:
            asked = self._ask(text)
            if chosen.get("kind") and chosen["kind"] != asked["kind"]:
                asked.pop("critique", None)              # set for the kind the model read, not the one chosen: the chosen kind's own default
            plan = self.normalise({**asked, **chosen, "production_id": production_id})
        except (AdapterError, KeyError, AttributeError, TypeError) as err:
            plan = self.normalise({"goal": text, **chosen, "production_id": production_id})
            mission_id = self.store.create(text, plan, [f"Mô hình chưa lập được kế hoạch ({getattr(err, 'message', None) or err}). Hãy chọn loại việc và sửa kế hoạch."])
            return self.view(mission_id)
        return self.view(self.store.create(text, plan, self.check(plan)))

    def edit(self, mission_id: str, changes: dict) -> dict:
        m = self._need(mission_id)
        if m["state"] not in ("draft", "planned"):
            raise ValueError("Kế hoạch đã xác nhận thì không sửa được nữa")
        plan = self.normalise({**m["plan"], **changes})
        self.store.replan(mission_id, plan, self.check(plan))
        return self.view(mission_id)

    # ------------------------------------------------------------------------------------------------------ carrying it out
    def confirm(self, mission_id: str) -> dict:
        """The operator's go: checked once more (budgets move), then started. Nothing runs before this."""
        m = self._need(mission_id)
        if m["state"] != "planned":
            raise ValueError("Chỉ kế hoạch đã lập xong, chưa chạy, mới xác nhận được")
        problems = self.check(m["plan"])
        if problems:
            self.store.replan(mission_id, m["plan"], problems)
            raise ValueError(" ".join(problems))
        plan = m["plan"]
        self.store.set_state(mission_id, "confirmed")
        if plan["kind"] in MAKES_VIDEOS:
            cap = round(plan["budget"] / plan["count"], 2) if plan["paid"] and plan["budget"] else 0.0       # no paid service without the permission
            # One production holds the mission's videos: the one it was given from, else a new one of its title.
            production = m.get("production_id") or self._new_production(plan["title"] or short_title(plan["goal"]))
            self.store.set_production(mission_id, production)
            for n in range(plan["count"]):
                goal = plan["goal"] if plan["count"] == 1 else f"{plan['goal']} (video {n + 1} trên {plan['count']}; khác các video còn lại)"
                title = plan["title"] or short_title(plan["goal"])
                title = title if plan["count"] == 1 else f"{short_title(title, 52)} · {n + 1}"
                task_id = self._producer.start(goal, title=title, format=plan["format"], lines=plan["lines"], use_stock=plan["stock"], critique=plan["critique"],
                                               production_id=production, topic=plan["kind"] == "topic", paid=plan["paid"],
                                               seconds=plan.get("seconds") or 180, form=plan.get("form") or DEFAULT_FORM)
                project_id = self._producer.task(task_id)["project_id"]
                self._prepare(project_id, {**plan, "budget_cap": cap})
                self.store.link(mission_id, tasks=[task_id], projects=[project_id])
        else:
            runs = self._start_library(plan["kind"])
            self.store.link(mission_id, runs=runs)
            if not runs:
                self.store.event(mission_id, "note", "Không có footage nào cần làm việc này.")
        return self.view(mission_id)

    def runs_of(self, m: dict) -> list[str]:
        """Every run a mission's work made: its own, and the ones its producer tasks started for their projects."""
        out = list(m["links"]["runs"])
        for project_id in m["links"]["projects"]:
            out += self._orch.runs_for_subject(project_id)           # a script from a topic is asked for the video, before it has a script
            for script_id in self._projects.script_ids(project_id):
                out += self._orch.runs_for_subject(script_id)
        return list(dict.fromkeys(out))

    def pause(self, mission_id: str) -> dict:
        m = self._need(mission_id)
        if m["state"] != "confirmed":
            raise ValueError("Chỉ nhiệm vụ đang chạy mới tạm dừng được")
        paused = sum(self._producer.pause(t) for t in m["links"]["tasks"])
        self.store.set_state(mission_id, "paused", note=f"{paused} việc của trợ lý dừng lại; bước nào đang chạy sẽ chạy xong.")
        return self.view(mission_id)

    def resume(self, mission_id: str) -> dict:
        m = self._need(mission_id)
        if m["state"] != "paused":
            raise ValueError("Nhiệm vụ không ở trạng thái tạm dừng")
        for t in m["links"]["tasks"]:
            self._producer.resume(t)
        self.store.set_state(mission_id, "confirmed", note="Tiếp tục.")
        return self.view(mission_id)

    def cancel(self, mission_id: str) -> dict:
        m = self._need(mission_id)
        if m["state"] == "cancelled":
            return self.view(mission_id)
        for t in m["links"]["tasks"]:
            self._producer.cancel(t)
        stopped = 0
        for r in self.runs_of(m):
            if self._orch.run_status(r).value in ("queued", "running", "waiting_review", "blocked"):
                self._orch.cancel_run(r)
                stopped += 1
        self.store.set_state(mission_id, "cancelled", note=f"Huỷ {len(m['links']['tasks'])} việc của trợ lý và {stopped} lượt chạy.")
        return self.view(mission_id)

    def retry(self, mission_id: str) -> dict:
        """Each failed stage of the mission's runs again, and each failed producer task from the step it stopped at."""
        m = self._need(mission_id)
        stages = 0
        for r in self.runs_of(m):
            for s in self._orch.stages(r):
                if s.status.value == "failed":
                    try:
                        self._orch.retry(s.stage_id)
                        stages += 1
                    except (ValueError, TypeError):
                        pass                                 # a stage that cannot be retried stays as it is, and says so in its run
        tasks = sum(self._producer.retry(t) for t in m["links"]["tasks"])
        self.store.event(mission_id, "retried", f"Chạy lại {stages} bước và {tasks} việc của trợ lý.")
        return self.view(mission_id)

    # ------------------------------------------------------------------------------------------------------ reading it
    def _need(self, mission_id: str) -> dict:
        m = self.store.get(mission_id)
        if m is None:
            raise LookupError(mission_id)
        return m

    def children(self, m: dict) -> list[dict]:
        """The work the mission started, each with its status and, beside it, what it is doing or waiting on."""
        out = []
        for t in m["links"]["tasks"]:
            task = self._producer.task(t)
            if task is None:
                continue
            out.append({"kind": "task", "id": t, "project_id": task["project_id"], "status": task["status"], "state": CHILD.get(task["status"], "running"),
                        "step": task["step"], "note": (task["log"][-1]["text"] if task["log"] else None)})
        window = self._orch.setting("background_window", "")
        for r in m["links"]["runs"]:
            info = self._orch.run_info(r)
            if info is None:
                continue
            status = self._orch.run_status(r).value
            stages = self._orch.stages(r)
            note = None
            if status == "running" and self._orch.stalled(r):
                note = "không thấy nhịp của máy làm; có thể đã treo"
            elif any(s.status.value == "retry_wait" for s in stages):
                note = "đang chờ để thử lại"
            elif info["pipeline_id"].startswith("library.") and status == "queued" and not in_window(window):
                note = "giữ tới giờ chạy nền"
            out.append({"kind": "run", "id": r, "pipeline": info["pipeline_id"], "subject_ref": info["subject_ref"], "status": status,
                        "state": "done" if status == "failed" and self._orch.cleared(r) else CHILD.get(status, "running"), "note": note})
        return out

    @staticmethod
    def derive(state: str, children: list[dict]) -> str:
        """The business status: the operator's own choices first, then what the children are doing."""
        if state in ("draft", "planned", "cancelled", "paused"):
            return state
        states = {c["state"] for c in children}
        if not children or states == {"done"}:
            return "completed"
        for live, status in (("waiting", "awaiting_approval"), ("blocked", "blocked"), ("running", "running"), ("paused", "running"), ("queued", "queued")):
            if live in states:
                return status
        if "done" in states:
            return "partially_completed"
        return "cancelled" if states == {"cancelled"} else "failed"

    def view(self, mission_id: str) -> dict:
        m = self._need(mission_id)
        children = self.children(m) if m["state"] in ("confirmed", "paused", "cancelled") else []
        runs = self.runs_of(m)
        return {**m, "kind_name": KINDS.get(m["plan"]["kind"], {}).get("name"), "status": self.derive(m["state"], children), "children": children,
                "spent": round(sum(self._orch.run_cost(r) for r in runs), 4), "run_ids": runs}

    def missions(self, *, production_id: str | None = None) -> list[dict]:
        return [self.view(m["mission_id"]) for m in self.store.missions(production_id=production_id)]
