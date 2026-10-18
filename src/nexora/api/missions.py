"""Mission Control's HTTP surface (design 2026-10-18): it reads what every service keeps and sends commands through their own
interfaces. Nothing here holds state of its own except what the mission store keeps."""
import os
import re
import shutil
import subprocess
import time

from fastapi import FastAPI, HTTPException

# What a running stage needs, as the engine the fleet lists it under (a stage asking for "model" keeps Ollama busy).
NEEDS = {"model": "ollama", "vision": "ollama", "embed": "ollama", "ffmpeg": "ffmpeg", "speech": "speech", "voice": "voice"}
ENGINE_OF = (("Ollama", "ollama"), ("Mô hình ", "ollama"), ("ffmpeg", "ffmpeg"), ("FFmpeg", "ffmpeg"), ("nhận dạng giọng nói", "speech"), ("Giọng đọc", "voice"))
GATES = {"sourcing.match": "Duyệt clip đã chọn", "edit.render": "Duyệt bản dựng", "edit.cut": "Duyệt bản dựng xuất ra", "sourcing.generate": "Duyệt hình sinh ra (tốn tiền)"}
HEAVY_RAM = 0.85                   # above this share of memory in use, a heavy 4K job should wait for the one before it


def machine(data_dir) -> dict:
    """This Mac, measured now: memory in use, load, disk."""
    out = {"cpus": os.cpu_count() or 1, "load": None, "memory_total": None, "memory_used": None, "disk_free": None, "disk_total": None}
    try:
        out["load"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    try:
        total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3).stdout.strip())
        vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
        page = int((re.search(r"page size of (\d+)", vm) or [None, 16384])[1])
        pages = {k.strip().lower(): int(v.strip().rstrip(".")) for k, v in re.findall(r"^([^:\n]+):\s+(\d+)\.?$", vm, re.M)}
        free = sum(pages.get(k, 0) for k in ("pages free", "pages inactive", "pages speculative", "pages purgeable")) * page
        out.update(memory_total=total, memory_used=max(0, total - free))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass                                          # not a Mac, or the tools are missing: memory is left unknown, not guessed
    disk = shutil.disk_usage(data_dir)
    out.update(disk_free=disk.free, disk_total=disk.total)
    return out


def verdict(qc: dict) -> str:
    """A cut's measured checks as one of four words."""
    if qc.get("external") or not qc.get("checks"):
        return "manual_review"                        # nothing was measured (an imported cut): a person has to look
    if not qc.get("passed"):
        return "fail"
    return "pass_with_warnings" if qc.get("findings") else "pass"


def add_missions(app: FastAPI, system, *, health) -> None:
    import json
    from nexora.agents.missions import KINDS
    from nexora.modules.planning.topic import FORMS as TOPIC_FORMS
    from nexora.app import PIPELINE_NAMES, capabilities, templates
    channels = lambda: json.loads(system.orch.setting("channels", "[]"))
    missions = system.missions
    seen_machine = {"at": 0.0, "value": None}

    def measured() -> dict:
        if time.time() - seen_machine["at"] > 5:
            seen_machine.update(at=time.time(), value=machine(system.data_dir))
        return seen_machine["value"]

    def project_title(pid: str | None) -> str:
        return ((system.projects.project(pid) if pid else None) or {}).get("title", "")

    def with_production(m: dict) -> dict:
        d = system.productions.get(m.get("production_id"))
        return {**m, "production": {"production_id": d["production_id"], "title": d["title"]} if d else None}

    def subject_project(subject: str) -> dict | None:
        if subject.startswith("cut_") and getattr(system, "cuts", None) is not None:
            cut = system.cuts.get(subject)                    # an exported cut of the Edit step names its project
            return system.projects.project(cut["project_id"]) if cut else None
        for p in system.projects.projects():
            if subject in system.projects.script_ids(p["project_id"]):
                return p
        return None

    def need(mission_id: str) -> dict:
        try:
            return missions.view(mission_id)
        except LookupError:
            raise HTTPException(404, "Không có nhiệm vụ này")

    def act(fn, mission_id: str, *args) -> dict:
        try:
            return fn(mission_id, *args)
        except LookupError:
            raise HTTPException(404, "Không có nhiệm vụ này")
        except ValueError as err:
            raise HTTPException(409, str(err))

    # ------------------------------------------------------------------------------------------------------ missions
    @app.get("/api/v1/missions")
    def list_missions(production: str = ""):
        """Every mission (or a production's), each with the production it works for; the work no mission started."""
        owned = system.missions.store.owner()
        system_work = []
        for run_id in system.orch.runs():
            if run_id in owned:
                continue
            info = system.orch.run_info(run_id)
            status = system.orch.run_status(run_id).value
            if status in ("queued", "running", "waiting_review", "blocked") or (status == "failed" and not system.orch.cleared(run_id)):
                project = subject_project(info["subject_ref"] or "")
                if project and project["project_id"] in owned:
                    continue                                  # made by a mission's producer task: listed under that mission
                system_work.append({"run_id": run_id, "pipeline": info["pipeline_id"], "name": PIPELINE_NAMES.get(info["pipeline_id"], info["pipeline_id"]),
                                    "status": status, "created_at": info["created_at"], "project_id": project and project["project_id"], "title": project and project["title"]})
        every = [with_production(m) for m in missions.missions(production_id=production.strip() or None)]
        named = {m["production"]["production_id"]: m["production"] for m in every if m["production"]}
        return {"missions": every, "productions": sorted(named.values(), key=lambda d: d["title"].lower()), "system": sorted(system_work, key=lambda r: -r["created_at"])[:60],
                "kinds": [{"kind": k, "name": v["name"]} for k, v in KINDS.items()],
                "forms": [{"key": k, "name": name} for k, (name, _) in TOPIC_FORMS.items()], "channels": [c["name"] for c in channels()], "templates": [t["name"] for t in templates(system)]}

    @app.post("/api/v1/missions", status_code=201)
    def plan_mission(body: dict):
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(422, "Hãy nói nhiệm vụ cần làm")
        return missions.plan(text, production_id=str(body.get("production_id") or "").strip() or None,
                             chosen={k: body.get(k) for k in ("kind", "form", "seconds")})

    @app.get("/api/v1/missions/{mission_id}")
    def mission_detail(mission_id: str):
        """A mission with its children's stages, attempts, events and cost, for the live monitor."""
        m = need(mission_id)
        runs = []
        for run_id in m["run_ids"]:
            info = system.orch.run_info(run_id)
            if info is None:
                continue
            stages = []
            for s in system.orch.stages(run_id):
                attempts = [{"number": a["number"], "outcome": a["outcome"], "started_at": a["started_at"], "seconds": round(a["ended_at"] - a["started_at"], 2) if a["ended_at"] else None,
                             "error_code": a["error_code"], "error_message": a["error_message"]} for a in system.orch.attempt_rows(s.stage_id)]
                stages.append({"stage_id": s.stage_id, "stage_key": s.stage_key, "status": s.status.value, "blocked_reason": s.blocked_reason, "attempts": attempts,
                               "outputs": s.outputs})
            runs.append({"run_id": run_id, "pipeline": info["pipeline_id"], "name": PIPELINE_NAMES.get(info["pipeline_id"], info["pipeline_id"]),
                         "status": system.orch.run_status(run_id).value, "created_at": info["created_at"], "cost": system.orch.run_cost(run_id), "stalled": system.orch.stalled(run_id),
                         "stages": stages, "events": [{"at": e.occurred_at, "kind": e.kind, "actor": e.actor} for e in system.orch.events(run_id)][-40:]})
        tasks = [t for t in (system.producer.task(t) for t in m["links"]["tasks"]) if t]
        return {**with_production(m), "runs": runs, "tasks": tasks, "projects": [{"project_id": p, "title": project_title(p)} for p in m["links"]["projects"]]}

    @app.patch("/api/v1/missions/{mission_id}")
    def edit_mission(mission_id: str, body: dict):
        return act(missions.edit, mission_id, dict(body.get("plan") or {}))

    for name in ("confirm", "pause", "resume", "cancel", "retry"):
        def command(mission_id: str, _name=name):
            return act(getattr(missions, _name), mission_id)
        app.add_api_route(f"/api/v1/missions/{{mission_id}}/{name}", command, methods=["POST"], name=f"mission_{name}")

    # ------------------------------------------------------------------------------------------------------ approvals
    def approvals() -> list[dict]:
        """Everything that waits for the operator, each saying who asks, why, what it touches, what it costs and what follows."""
        out = []
        for m in missions.store.missions():
            if m["state"] == "planned":
                plan = m["plan"]
                out.append({"key": f"mission:{m['mission_id']}", "kind": "mission", "id": m["mission_id"], "title": m["text"], "asked_by": "Mission Composer",
                            "why": "Kế hoạch đã lập, chờ bạn xác nhận trước khi chạy.", "touches": f"{plan['count']} video" if plan["kind"] in ("video", "topic") else plan["kind"],
                            "cost": plan.get("budget"), "next": "Xác nhận thì hệ thống bắt đầu làm; không xác nhận thì không có gì chạy.", "at": m["created_at"],
                            "actions": ["confirm", "cancel"], "link": None})
        seen = set()
        waiting_projects = set()
        for run_id in sorted(system.orch.runs(), key=lambda r: system.orch.run_info(r)["created_at"], reverse=True):
            info = system.orch.run_info(run_id)
            project = subject_project(info["subject_ref"] or "")
            key = (project["project_id"] if project else info["subject_ref"], info["pipeline_id"])
            if key in seen:
                continue                                       # only the newest run of a piece of work speaks for it
            seen.add(key)
            status = system.orch.run_status(run_id).value
            if status not in ("waiting_review", "blocked"):
                continue
            stage = next((s for s in system.orch.stages(run_id) if s.status.value == status), None)
            if stage is None:
                continue
            if project:
                waiting_projects.add(project["project_id"])
            where = project["title"] if project else (info["subject_ref"] or "")
            pipeline = info["pipeline_id"]
            link = (f"/du-an/{project['project_id']}/storyboard" if pipeline == "sourcing.match" else f"/du-an/{project['project_id']}") if project else "/tien-trinh"
            if status == "waiting_review":
                actions = ["approve", "changes"] if pipeline == "edit.render" else ([] if pipeline in GATES else ["approve", "reject"])
                out.append({"key": f"gate:{stage.stage_id}", "kind": "gate", "id": stage.stage_id, "pipeline": pipeline, "project_id": project and project["project_id"],
                            "title": f"{GATES.get(pipeline, 'Duyệt bước ' + stage.stage_key)}: {where}", "asked_by": PIPELINE_NAMES.get(pipeline, pipeline),
                            "why": "Cổng duyệt: bước sau chỉ chạy khi bạn đồng ý.", "touches": where, "cost": system.orch.run_cost(run_id) or None,
                            "next": "Duyệt thì quy trình chạy tiếp; trả lại thì nó dừng ở đây.", "at": info["created_at"], "actions": actions, "link": link})
            else:
                out.append({"key": f"blocked:{stage.stage_id}", "kind": "blocked", "id": stage.stage_id, "pipeline": pipeline, "project_id": project and project["project_id"],
                            "title": f"Đang dừng: {PIPELINE_NAMES.get(pipeline, pipeline)} · {where}", "asked_by": PIPELINE_NAMES.get(pipeline, pipeline),
                            "why": stage.blocked_reason or "Bước này cần bạn xử lý trước khi chạy tiếp.", "touches": where, "cost": None,
                            "next": "Xử lý xong lý do rồi cho chạy tiếp.", "at": info["created_at"], "actions": ["resume"], "link": link})
        for t in system.producer.tasks():
            if t["status"] == "waiting_operator" and t["project_id"] not in waiting_projects:
                out.append({"key": f"task:{t['task_id']}", "kind": "task", "id": t["task_id"], "project_id": t["project_id"], "title": f"Trợ lý chờ bạn: {project_title(t['project_id'])}",
                            "asked_by": "Producer", "why": t["log"][-1]["text"] if t["log"] else "Chờ bạn.", "touches": project_title(t["project_id"]), "cost": None,
                            "next": "Trợ lý làm tiếp khi bạn đã xem và duyệt.", "at": t["updated_at"], "actions": [], "link": f"/du-an/{t['project_id']}" + ("/storyboard" if t["step"] == "review" else "")})
        for idea in system.planning.ideas.ideas(status=("blocked",)) if system.planning.ideas else []:
            out.append({"key": f"idea:{idea['idea_id']}", "kind": "idea", "id": idea["idea_id"], "title": f"Ý tưởng bị chặn: {idea['title']}", "asked_by": "Tìm ý tưởng",
                        "why": idea.get("risk") or "Có rủi ro.", "touches": f"{idea['material']['kind']}: {idea['material']['name']}", "cost": None,
                        "next": "Chỉ làm được khi bạn ghi lý do vẫn làm.", "at": idea["created_at"], "actions": [], "link": "/du-an?y-tuong=1"})
        if system.storyboard is not None:
            for p in system.projects.projects():
                for msg in system.storyboard.messages(p["project_id"], limit=50):
                    if msg["proposal"] and msg["status"] == "open":
                        out.append({"key": f"proposal:{msg['message_id']}", "kind": "proposal", "id": msg["message_id"], "project_id": p["project_id"],
                                    "title": f"Đề xuất của {msg['role']}: {p['title']}", "asked_by": msg["role"], "why": msg["text"][:240], "touches": p["title"], "cost": None,
                                    "next": "Áp dụng thì Storyboard đổi theo; bỏ qua thì giữ nguyên.", "at": msg["at"], "actions": [], "link": f"/du-an/{p['project_id']}/storyboard"})
        if system.vq_reader is not None:
            waiting = [sub for sub in system.vq_reader.subjects() if (sub.get("recipe") or {}).get("status") == "proposed"]
            if waiting:                                        # one line for them all: each is decided on the VQ screen, never from here
                names = list(dict.fromkeys(os.path.basename(sub.get("path") or "") or sub["subject"] for sub in waiting))
                out.append({"key": "vq", "kind": "vq", "id": "vq", "title": f"{len(waiting)} công thức làm nét chờ duyệt ({len(names)} file)", "asked_by": "Visual Quality",
                            "why": "Mỗi công thức chỉ được áp khi bạn duyệt nó trên màn hình VQ.", "touches": ", ".join(names[:6]) + (f" và {len(names) - 6} file khác" if len(names) > 6 else ""),
                            "cost": None, "next": "Chưa duyệt thì footage dùng bản gốc.", "at": max(sub["recipe"]["at"] for sub in waiting), "actions": [], "link": "/chat-luong-hinh"})
        return sorted(out, key=lambda a: -(a["at"] or 0))

    @app.get("/api/v1/approvals")
    def list_approvals():
        return {"approvals": approvals()}

    @app.post("/api/v1/approvals/decide")
    def decide(body: dict):
        """The decisions simple enough to make from the list; everything else opens where it is looked at."""
        kind, ident, decision, note = body.get("kind"), str(body.get("id") or ""), body.get("decision"), str(body.get("note") or "").strip() or None
        try:
            if kind == "mission" and decision in ("confirm", "cancel"):
                return getattr(missions, decision)(ident)
            if kind == "blocked" and decision == "resume":
                system.orch.resume(ident)
                return {"ok": True}
            if kind == "gate" and decision in ("approve", "reject", "changes"):
                item = next((a for a in approvals() if a["key"] == f"gate:{ident}"), None)
                if item is None:
                    raise HTTPException(409, "Cổng duyệt này không còn chờ nữa")
                if decision not in item["actions"]:
                    raise HTTPException(409, "Việc này cần mở ra xem rồi mới duyệt được")
                approve = decision == "approve"
                if decision == "changes" and not note:
                    raise HTTPException(422, "Hãy ghi cần sửa gì")
                if item["pipeline"] == "edit.render" and item["project_id"]:
                    latest = system.projects.renders(item["project_id"])
                    if latest:
                        system.projects.set_render_review(latest[0]["render_id"], approved=approve, comment=note)
                system.orch.decide_review(ident, approve=approve)
                return {"ok": True}
        except LookupError:
            raise HTTPException(404, "Không tìm thấy")
        except ValueError as err:
            raise HTTPException(409, str(err))
        raise HTTPException(422, "Không có quyết định này")

    # ------------------------------------------------------------------------------------------------------ the fleet
    def fleet() -> dict:
        """Agents, workers and engines, each in one of five states read from real checks."""
        checks = health()
        kill = system.orch.kill_switch()
        busy_engines = set()
        live_pipelines = set()
        for run_id in system.orch.runs():
            if system.orch.run_status(run_id).value != "running":
                continue
            try:
                pipeline = system.registry.definition(system.orch.pipeline_of(run_id))
            except (KeyError, LookupError):
                pipeline = None
            live_pipelines.add(system.orch.pipeline_of(run_id))
            for s in system.orch.stages(run_id):
                if s.status.value == "running" and pipeline is not None:
                    spec = next((x for x in pipeline.stages if x.key == s.stage_key), None)
                    busy_engines |= {NEEDS[r.partition(".")[0]] for r in (spec.requires if spec else ()) if r.partition(".")[0] in NEEDS}
        engines: dict[str, dict] = {}
        for c in checks:
            kind = next((k for marker, k in ENGINE_OF if marker in c["name"]), None)
            if c["ok"]:
                state = "busy" if kind in busy_engines else "healthy"
            else:
                state = "disabled" if c["optional"] else "offline"
            if kind == "ollama" and c["name"].startswith("Mô hình ") and not c["ok"]:
                state = "degraded"                           # Ollama runs, one model it is asked for is not there
            engines[c["name"]] = {"key": c["name"], "name": c["name"], "group": "engine", "state": state, "detail": c["detail"], "fix": c["fix"], "engine": kind}
        model_ok = any(e["engine"] == "ollama" and e["state"] in ("healthy", "busy") for e in engines.values() if e["name"].startswith("Ollama"))
        model_degraded = any(e["state"] == "degraded" for e in engines.values() if e["engine"] == "ollama")

        def needs_model(busy: bool, detail: str) -> tuple[str, str]:
            if kill:
                return "disabled", "Dừng khẩn cấp đang bật."
            if not model_ok:
                return "offline", "Không kết nối được Ollama, nên không có mô hình để làm việc."
            if busy:
                return "busy", detail
            return ("degraded", "Thiếu một mô hình được yêu cầu; " + detail) if model_degraded else ("healthy", detail)

        tasks = system.producer.tasks()
        working = [t for t in tasks if t["status"] == "working"]
        waiting = [t for t in tasks if t["status"] == "waiting_operator"]
        ideas = getattr(app.state, "ideas", {}) or {}
        level = system.autonomy.level
        agents = []
        for key, name, role, busy, detail in (
            ("producer", "Producer", "Nhận mục tiêu, đưa một video qua các bước", bool(working), f"{len(working)} việc đang làm, {len(waiting)} chờ bạn."),
            ("director", "Director", "Đưa từng cảnh Storyboard tới lúc được nhận", False, "Chạy khi bạn bấm trong Storyboard."),
            ("copilot", "Copilot", "Rút gọn bản ghi có người nói thành bản dựng thô", False, "Chạy khi bạn hỏi trong Storyboard."),
            ("ideas", "Tìm ý tưởng", "Đề xuất video làm được từ kho", bool(ideas.get("running")), ideas.get("error") or ("Đang gợi ý." if ideas.get("running") else "Tự gợi ý lại khi kho đổi hoặc mỗi tuần.")),
            ("composer", "Mission Composer", "Đổi lời giao việc thành kế hoạch", False, "Lập kế hoạch khi bạn giao việc."),
        ):
            state, said = needs_model(busy, detail)
            agents.append({"key": key, "name": name, "group": "agent", "role": role, "state": state, "detail": said})
        agents.append({"key": "autonomy", "name": "Autonomy", "group": "agent", "role": "Quyết định hệ thống được tự làm tới đâu", "state": "disabled" if kill else "healthy",
                       "detail": f"Mức {level}." + (" Dừng khẩn cấp đang bật." if kill else "")})
        load = system.orch.lane_load()
        from nexora.core.schedule import in_window
        window = system.orch.setting("background_window", "")
        stalled = [r for r in system.orch.runs() if system.orch.run_status(r).value == "running" and system.orch.stalled(r)]
        workers = []
        for lane, name in (("interactive", "Làn tương tác"), ("background", "Làn chạy nền")):
            q = load.get(lane, {"ready": 0, "running": 0, "retry_wait": 0, "costly_running": 0})
            held = lane == "background" and not in_window(window)
            if kill:
                state, detail = "disabled", "Dừng khẩn cấp đang bật."
            elif stalled and q["running"]:
                state, detail = "degraded", f"{len(stalled)} lượt chạy không còn thấy nhịp của máy làm."
            elif q["running"]:
                state, detail = "busy", f"{q['running']} bước đang chạy, {q['ready']} chờ."
            elif held and q["ready"]:
                state, detail = "disabled", f"{q['ready']} bước chờ tới giờ chạy nền ({window})."
            else:
                state, detail = "healthy", f"{q['ready']} bước chờ." if q["ready"] else "Rảnh."
            workers.append({"key": lane, "name": name, "group": "worker", "state": state, "detail": detail, "queue": q})
        return {"agents": agents, "workers": workers, "engines": list(engines.values()), "live_pipelines": sorted(live_pipelines)}

    @app.get("/api/v1/fleet")
    def get_fleet():
        return fleet()

    # ------------------------------------------------------------------------------------------------------ quality, artifacts
    @app.get("/api/v1/quality")
    def quality():
        rows = []
        for p in system.projects.projects():
            for n, r in enumerate(system.projects.renders(p["project_id"])):
                qc = r["qc"]
                review = r["review"]
                rows.append({"render_id": r["render_id"], "project_id": p["project_id"], "title": p["title"], "created_at": r["created_at"], "verdict": verdict(qc),
                             "duration": qc.get("duration"), "width": qc.get("width"), "height": qc.get("height"),
                             "failed": [k for k, ok in (qc.get("checks") or {}).items() if not ok], "findings": [f.get("check") or f.get("text") or str(f) if isinstance(f, dict) else str(f) for f in qc.get("findings", [])][:8],
                             "review": "approved" if (review or {}).get("approved") else "changes" if review else ("waiting" if n == 0 else "none"),
                             "comment": (review or {}).get("comment")})
        rows.sort(key=lambda r: -r["created_at"])
        counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("pass", "pass_with_warnings", "fail", "manual_review")}
        return {"renders": rows[:120], "counts": counts}

    @app.get("/api/v1/artifacts")
    def artifacts():
        """Per project, what it was made from and what it made: footage, script versions, cuts, packages. Links only."""
        owned = missions.store.owner()
        out = []
        projects = sorted(system.projects.projects(), key=lambda p: (p["project_id"] not in owned, -p["created_at"]))[:30]
        for p in projects:
            script = system.projects.current_script(p["project_id"])
            sources = sorted({s.asset_id for s in system.projects.selections(script["script_id"]) if getattr(s, "asset_id", None)}) if script else []
            renders = system.projects.renders(p["project_id"])
            out.append({"project_id": p["project_id"], "title": p["title"], "mission_id": owned.get(p["project_id"]), "created_at": p["created_at"],
                        "sources": len(sources), "scripts": len(system.projects.script_ids(p["project_id"])), "script_version": script["version"] if script else None,
                        "renders": [{"render_id": r["render_id"], "created_at": r["created_at"], "verdict": verdict(r["qc"]), "approved": bool((r["review"] or {}).get("approved")),
                                     "packaged": bool(system.distribution.package(r["render_id"]))} for r in renders[:6]]})
        return {"projects": out}

    # ------------------------------------------------------------------------------------------------------ overview, resources, logs
    def budgets() -> dict:
        t = time.localtime()
        day, month = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)), time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        number = lambda key: float(v) if (v := system.orch.setting(key, "")) not in (None, "") else None
        return {"spent_today": system.orch.spent_since(day), "spent_month": system.orch.spent_since(month), "budget_day": number("budget_day"), "budget_month": number("budget_month"),
                "by_day": system.orch.spend_by_day(), "providers": system.orch.usage(since=month)}

    @app.get("/api/v1/resources")
    def resources():
        load = system.orch.lane_load()
        m = measured()
        heavy = sum(q["running"] for q in load.values())
        pressure = (m["memory_used"] / m["memory_total"]) if m["memory_used"] and m["memory_total"] else None
        return {"machine": m, "lanes": load, "running": heavy, "memory_pressure": pressure, "hold_heavy": pressure is not None and pressure > HEAVY_RAM, **budgets()}

    @app.get("/api/v1/mission-control")
    def overview():
        every = missions.missions()
        active = [m for m in every if m["status"] in ("queued", "running", "awaiting_approval", "blocked", "paused")]
        waits = approvals()
        crew = fleet()
        states = [x["state"] for group in ("agents", "workers", "engines") for x in crew[group]]
        failed = [r for r in system.orch.runs() if system.orch.run_status(r).value == "failed" and not system.orch.cleared(r)]
        alerts = [{"kind": "offline", "text": f"{e['name']}: {e['detail']}", "link": "/he-thong"} for e in crew["engines"] if e["state"] == "offline"]
        alerts += [{"kind": "failed", "text": f"{len(failed)} lượt chạy lỗi chưa xem", "link": "/tien-trinh"}] if failed else []
        res = resources()
        if res["hold_heavy"]:
            alerts.append({"kind": "memory", "text": "Bộ nhớ gần đầy: việc nặng nên chạy lần lượt", "link": None})
        if res["budget_day"] is not None and res["spent_today"] >= res["budget_day"]:
            alerts.append({"kind": "budget", "text": "Đã tiêu hết ngân sách hôm nay", "link": "/chi-phi"})
        return {"kpis": {"active": len(active), "awaiting": len(waits), "missions": len(every), "health": {s: states.count(s) for s in ("healthy", "busy", "degraded", "offline", "disabled")},
                         "alerts": len(alerts)},
                "active": active[:8], "approvals": waits[:6], "alerts": alerts, "resources": res, "fleet": crew, "kill_switch": system.orch.kill_switch(),
                "autonomy": system.autonomy.level, "unavailable": [c["pipeline"] for c in capabilities(system) if not c["available"]]}

    @app.get("/api/v1/logs")
    def logs(kind: str = "", limit: int = 200):
        """The record, newest first: missions' events, runs' events, every change made through the interface, notifications."""
        out = []
        for m in missions.store.missions(limit=100):
            out += [{"at": e["at"], "kind": "mission", "level": "info", "source": m["text"][:60], "text": f"{e['kind']}" + (f": {e['text']}" if e.get("text") else ""), "ref": m["mission_id"]}
                    for e in m["events"]]
        for run_id in sorted(system.orch.runs(), key=lambda r: system.orch.run_info(r)["created_at"], reverse=True)[:40]:
            name = PIPELINE_NAMES.get(system.orch.pipeline_of(run_id), system.orch.pipeline_of(run_id))
            for e in system.orch.events(run_id):
                level = "error" if "fail" in e.kind else "warn" if e.kind in ("blocked", "cancelled", "retry_scheduled") else "info"
                out.append({"at": e.occurred_at, "kind": "run", "level": level, "source": name, "text": e.kind, "ref": run_id})
        out += [{"at": a["at"], "kind": "audit", "level": "warn" if a["status"] >= 400 else "info", "source": a["method"], "text": a["path"], "ref": None}
                for a in system.orch.audit_log(limit=200)]
        out += [{"at": n["created_at"], "kind": "notice", "level": "warn" if n["kind"] in ("failed", "blocked") else "info", "source": n["kind"], "text": n.get("reason") or n.get("stage_key") or n["kind"],
                 "ref": n["run_id"]} for n in system.orch.notifications(limit=100) if "created_at" in n]
        if kind:
            out = [e for e in out if e["kind"] == kind]
        out.sort(key=lambda e: -(e["at"] or 0))
        return {"entries": out[:max(1, min(1000, limit))]}
