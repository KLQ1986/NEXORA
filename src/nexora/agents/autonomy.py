"""How much the system may decide on its own (design v4.0, section 10).

Five levels, each adding one decision to those below it. A level can only be chosen once the operator's own record
shows it is earned: enough reviews at the gate it would take over, with the recent ones all approved. The record is
read from the event log, which no setting can edit. When the operator turns down a cut while the system holds the
right to approve cuts, that right is given back at once.

Beside the levels, the operator may switch approving on for a gate on their own, with no record to earn, and off again:
clips (when every line has a picture), cuts (when they pass every check), and pictures made by paid services (within
the budget). Turning down a cut while cuts are approved on their own switches that back off.

Whatever the level or switch, a kill switch, a budget and privacy mode are obeyed first: this module only presses
"approve" where a person would otherwise be asked, and every such press is recorded with `policy` as its author.
"""
import json
import time

from nexora.core.states import StageStatus

LEVELS = [
    {"level": 0, "name": "Thủ công", "does": "Hệ thống chỉ làm khi bạn bấm. Không có gì được tự duyệt, kể cả ở dự án bật tự duyệt clip."},
    {"level": 1, "name": "Đề xuất", "does": "Hệ thống đề xuất clip và bản dựng; bạn duyệt ở mọi cổng. Dự án nào bật tự duyệt clip thì dự án đó được tự duyệt."},
    {"level": 2, "name": "Tự duyệt clip", "does": "Ở mọi dự án, clip được tự duyệt khi mọi câu có hình và mô hình chấm chắc chắn."},
    {"level": 3, "name": "Tự duyệt bản dựng", "does": "Thêm: bản dựng đạt kiểm tra, không có điểm nghiêm trọng và không phải bản nháp thì được tự duyệt."},
    {"level": 4, "name": "Tự đóng gói", "does": "Thêm: bản dựng đã duyệt và đủ điều kiện bản quyền thì được đóng gói và đưa vào thư mục xuất bản."},
]
NEED = {2: ("sourcing.match", 5), 3: ("edit.render", 5), 4: ("edit.render", 8)}       # the gate whose record counts, and how many reviews it takes
RECENT = 5                                                                           # of which this many most recent must all be approvals
SWITCHES = {"clips": "Tự duyệt clip", "renders": "Tự duyệt bản dựng", "pictures": "Tự duyệt hình AI (tốn tiền)"}


class Autonomy:
    def __init__(self, orch, projects, *, package=None, publish=None, rights=None, approve_clips=None, cut_gate=None, approve_pictures=None):
        self._orch, self._projects = orch, projects
        self._package, self._publish, self._rights = package, publish, rights       # given by the composition root; any may be absent
        # (project_id, run_id) -> None approves a clip match as the storyboard does; (project_id) -> stage_id of the cut waiting
        # for review (a render or an export of the Edit step), or None; (run_id) -> None approves a generation's waiting gate.
        self._approve_clips, self._cut_gate, self._approve_pictures = approve_clips, cut_gate, approve_pictures

    @property
    def level(self) -> int:
        return int(self._orch.setting("autonomy_level", "1"))

    def record(self, pipeline: str) -> dict:
        """The operator's reviews at one gate: how many, and how the most recent went."""
        decisions = [d for d in self._orch.decisions(pipeline) if d["actor"] == "operator"]
        recent = decisions[:RECENT]
        return {"reviews": len(decisions), "recent_approved": sum(d["approve"] for d in recent), "recent": len(recent)}

    def status(self) -> dict:
        levels = []
        for item in LEVELS:
            need = NEED.get(item["level"])
            if need is None:
                levels.append({**item, "earned": True, "progress": None})
                continue
            rec = self.record(need[0])
            earned = rec["reviews"] >= need[1] and rec["recent"] >= RECENT and rec["recent_approved"] == RECENT
            if item["level"] == 4:
                earned = earned and self._publish is not None
            gate = "duyệt clip" if need[0] == "sourcing.match" else "duyệt bản dựng"
            levels.append({**item, "earned": earned, "progress": {"have": rec["reviews"], "need": need[1], "recent_approved": rec["recent_approved"], "recent_need": RECENT,
                                                                   "text": f"Cần {need[1]} lần {gate} do chính bạn làm, trong đó {RECENT} lần gần nhất đều là duyệt. Hiện có {rec['reviews']} lần, {rec['recent_approved']} trên {rec['recent']} lần gần nhất là duyệt."
                                                                           + (" Máy này chưa có thư mục xuất bản." if item["level"] == 4 and self._publish is None else "")}})
        return {"level": self.level, "levels": levels, "switches": self.switches(), "switch_names": SWITCHES,
                "log": json.loads(self._orch.setting("autonomy_log", "[]"))[-10:]}

    def switches(self) -> dict[str, bool]:
        kept = json.loads(self._orch.setting("auto_approve", "{}"))
        return {k: bool(kept.get(k)) for k in SWITCHES}

    def set_switches(self, changes: dict) -> dict:
        """Turn approving on or off for some gates, as the operator chooses; nothing to earn first."""
        now = self.switches()
        for key, on in changes.items():
            if key in SWITCHES and bool(on) != now[key]:
                now[key] = bool(on)
                self._log(f"Bạn {'bật' if on else 'tắt'} {SWITCHES[key].lower()}.", self.level)
                if key == "renders" and on:
                    self._orch.set_setting("auto_approve_since", str(time.time()))
        self._orch.set_setting("auto_approve", json.dumps(now))
        return self.status()

    def _log(self, text: str, level: int) -> None:
        log = json.loads(self._orch.setting("autonomy_log", "[]"))
        log.append({"at": time.time(), "level": level, "text": text})
        self._orch.set_setting("autonomy_log", json.dumps(log[-50:], ensure_ascii=False))

    def set_level(self, level: int) -> dict:
        """Choose a level. Going down is always allowed; going up only to a level that has been earned, and every level below it too."""
        if not 0 <= level <= 4:
            raise ValueError("no such level")
        status = self.status()
        if level > self.level and not all(l["earned"] for l in status["levels"] if l["level"] <= level):
            raise PermissionError(next(l["progress"]["text"] for l in status["levels"] if l["level"] <= level and not l["earned"]))
        self._orch.set_setting("autonomy_level", str(level))
        self._orch.set_setting("autonomy_since", str(time.time()))
        self._log(f"Bạn chọn mức {level}: {LEVELS[level]['name']}.", level)
        return self.status()

    def clips_may_be_accepted(self, project: dict) -> bool:
        """Whether a confident match may be accepted without review for this project."""
        return self.level >= 2 or self.switches()["clips"] or (self.level == 1 and bool(project.get("auto_accept")))

    def tick(self) -> list[str]:
        """Take the decisions the current level and the operator's switches allow. Returns what was done, in words."""
        done, level, switches = [], self.level, self.switches()
        since = float(self._orch.setting("autonomy_since", "0"))
        # Trust is given back the moment the operator turns down a cut.
        if level >= 3 and self._refused_since(since):
            self._orch.set_setting("autonomy_level", "2")
            self._orch.set_setting("autonomy_since", str(time.time()))
            self._log("Bạn vừa từ chối một bản dựng, nên quyền tự duyệt bản dựng được trả lại. Mức hiện tại: 2.", 2)
            self._orch.notify("autonomy_lowered", "", reason="Tự duyệt bản dựng đã tắt vì bạn vừa từ chối một bản dựng.")
            return ["demoted"]
        if switches["renders"] and self._refused_since(float(self._orch.setting("auto_approve_since", "0"))):
            self.set_switches({"renders": False})
            self._orch.notify("autonomy_lowered", "", reason="Tự duyệt bản dựng đã tắt vì bạn vừa từ chối một bản dựng.")
            return ["demoted"]
        if self._orch.kill_switch():
            return done
        if switches["clips"] and self._approve_clips is not None:
            done += self._clips()
        if switches["pictures"] and self._approve_pictures is not None:
            for run_id, _ in self._orch.waiting_review("sourcing.generate"):
                self._approve_pictures(run_id)
                self._log("Tự duyệt hình AI của một kịch bản.", level)
                done.append(f"pictures:{run_id}")
        if level < 3 and not switches["renders"]:
            return done
        for project in self._projects.projects():
            script = self._projects.current_script(project["project_id"])
            renders = self._projects.renders(project["project_id"])
            if not script or not renders or (not switches["renders"] and renders[0]["created_at"] < since):
                continue
            latest = renders[0]
            if self._cut_gate is not None:
                gate = self._cut_gate(project["project_id"])
            else:
                run = next((r for r in self._orch.runs_for_subject(script["script_id"]) if self._orch.pipeline_of(r) == "edit.render"), None)
                gate = next((s.stage_id for s in self._orch.stages(run) if s.status is StageStatus.WAITING_REVIEW), None) if run else None
            qc = latest["qc"]
            if gate and latest["script_id"] == script["script_id"] and latest["review"] is None:
                serious = [f for f in qc.get("findings", []) if f.get("severity") == "cao"]
                if qc.get("passed") and not qc.get("draft") and not serious and not qc.get("gaps"):
                    self._orch.decide_review(gate, approve=True, actor="policy")
                    self._projects.set_render_review(latest["render_id"], approved=True, comment="Tự duyệt: đạt mọi kiểm tra, không có điểm nghiêm trọng.")
                    self._log(f"Tự duyệt bản dựng của “{project['title']}”.", level)
                    done.append(f"approved:{latest['render_id']}")
                    latest = self._projects.render(latest["render_id"])
            if level >= 4 and self._package and self._publish and self._rights and (latest["review"] or {}).get("approved") and not qc.get("external"):
                state = self._package(latest["render_id"], peek=True)
                if state is None and self._rights(latest["render_id"])["clear"]:
                    self._package(latest["render_id"])
                    self._publish(latest["render_id"])
                    self._log(f"Đóng gói và đưa “{project['title']}” vào thư mục xuất bản.", level)
                    done.append(f"published:{latest['render_id']}")
        return done

    def _refused_since(self, since: float) -> bool:
        return any(d["actor"] == "operator" and not d["approve"] and d["at"] > since for d in self._orch.decisions("edit.render"))

    def _clips(self) -> list[str]:
        """Clip matches waiting at their gate with a picture for every line, approved as the storyboard approves them. One
        with a line still without a picture waits for the operator: approving it would cut a video with a hole in it."""
        done = []
        for run_id, _ in self._orch.waiting_review("sourcing.match"):
            script_id = self._orch.run_info(run_id)["subject_ref"]
            script = self._projects.script(script_id)
            project = self._projects.project(script["project_id"]) if script else None
            if project is None or project.get("trashed_at") or self._projects.current_script(project["project_id"])["script_id"] != script_id:
                continue
            if any(s.status == "gap" for s in self._projects.selections(script_id)):
                continue
            self._approve_clips(project["project_id"], run_id)
            self._log(f"Tự duyệt clip của “{project['title']}”.", self.level)
            done.append(f"clips:{project['project_id']}")
        return done
