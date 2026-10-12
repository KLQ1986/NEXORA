"""Editing by word: the operator says what to change, and the change is proposed as a list of plain operations.

A model reads the instruction, but it can only choose from a fixed set of operations on numbered lines, and nothing is
done until the operator has seen the list and applied it. An instruction the model turns into nothing valid changes
nothing. It sits above the modules because one sentence may touch the script, the clips and the cut at once.
"""
from nexora.core.adapter import PrivacyClass, Request

TEXT_ONLY = PrivacyClass.CLOUD_ALLOWED       # a prompt of words alone: it may be served by a cloud model if the operator routes it there

PROMPT = (
    "Đây là các câu của một video đang dựng, kèm tình trạng hình của từng câu:\n{lines}\n\n"
    "Người dựng yêu cầu: \"{text}\"\n\n"
    "Chuyển yêu cầu thành danh sách thao tác. Chỉ dùng các loại sau, mỗi thao tác là một mục JSON:\n"
    "- doi_clip (cau): đổi câu sang clip phương án khác\n- bo_clip (cau): bỏ clip của câu, để trống hình\n"
    "- cat_ngan (cau, giay): clip của câu chỉ dài chừng đó giây\n- bo_cau (cau): xoá câu khỏi kịch bản\n"
    "- chuyen (cau, den): đưa câu tới vị trí khác\n- toc_do (cau, gia_tri): tốc độ hình, một trong 0.5, 0.75, 1, 1.5, 2\n"
    "- chong_rung (cau): bật chống rung\n- sua_loi (cau, loi_moi): đổi lời của câu\n"
    "Nếu yêu cầu không ứng với loại nào thì trả về danh sách rỗng. Chỉ trả về JSON với khoá thao_tac."
)
MAX_OPS = 12


class Commands:
    def __init__(self, adapters, projects, sourcing, edit):
        self._adapters, self._projects, self._sourcing, self._edit = adapters, projects, sourcing, edit

    def propose(self, project_id: str, text: str) -> list[dict]:
        """What the instruction would do, as operations the operator can read. Anything that names a line that does not exist,
        or asks for something a line cannot do, is left out."""
        script = self._projects.current_script(project_id)
        shots = script["shots"] if script else []
        if not shots or not text.strip():
            return []
        state = lambda sel: "chưa tìm clip" if sel is None else "thiếu hình" if sel.status == "gap" else f"có clip, {len(sel.alternates)} phương án khác"
        lines = "\n".join(f"{i}. {s.text} ({state(self._projects.selection(s.shot_id))})" for i, s in enumerate(shots, 1))
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": PROMPT.format(lines=lines, text=text.strip()), "json": True, "max_tokens": 400, "task": "command"})).outputs["json"]
        ops = []
        for raw in (out.get("thao_tac") or [])[:MAX_OPS]:
            op = self._valid(raw, shots)
            if op:
                ops.append(op)
        return ops

    def _valid(self, raw, shots) -> dict | None:
        try:
            kind, n = str(raw.get("loai", "")), int(raw.get("cau"))
        except (AttributeError, TypeError, ValueError):
            return None
        if not 1 <= n <= len(shots):
            return None
        sel = self._projects.selection(shots[n - 1].shot_id)
        has_clip = sel is not None and sel.status != "gap" and sel.asset_id
        try:
            if kind == "doi_clip" and has_clip and sel.alternates:
                return {"op": "swap", "line": n, "describe": f"Câu {n}: đổi sang clip phương án khác."}
            if kind == "bo_clip" and has_clip:
                return {"op": "gap", "line": n, "describe": f"Câu {n}: bỏ clip, để trống hình."}
            if kind == "cat_ngan" and has_clip and 0.5 <= float(raw["giay"]) <= 60:
                return {"op": "trim", "line": n, "seconds": round(float(raw["giay"]), 1), "describe": f"Câu {n}: clip chỉ dài {float(raw['giay']):.1f} giây."}
            if kind == "bo_cau" and len(shots) > 1:
                return {"op": "remove", "line": n, "describe": f"Xoá câu {n}: “{shots[n - 1].text}”"}
            if kind == "chuyen" and 1 <= int(raw["den"]) <= len(shots) and int(raw["den"]) != n:
                return {"op": "move", "line": n, "to": int(raw["den"]), "describe": f"Đưa câu {n} tới vị trí {int(raw['den'])}."}
            if kind == "toc_do" and has_clip and float(raw["gia_tri"]) in (0.5, 0.75, 1.0, 1.5, 2.0):
                return {"op": "speed", "line": n, "value": float(raw["gia_tri"]), "describe": f"Câu {n}: hình chạy ở tốc độ {float(raw['gia_tri']):g} lần."}
            if kind == "chong_rung" and has_clip:
                return {"op": "stabilise", "line": n, "describe": f"Câu {n}: bật chống rung."}
            if kind == "sua_loi" and str(raw["loi_moi"]).strip() and str(raw["loi_moi"]).strip() != shots[n - 1].text:
                return {"op": "text", "line": n, "text": str(raw["loi_moi"]).strip(), "describe": f"Câu {n}: đổi lời thành “{str(raw['loi_moi']).strip()}”. Clip của câu phải tìm lại."}
        except (KeyError, TypeError, ValueError):
            return None
        return None

    def apply(self, project_id: str, ops: list[dict]) -> dict:
        """Carry out operations that `propose` returned. Changes to clips are made first; changes to the script itself (a line
        removed, moved or reworded) then become one new version, in which every untouched line keeps its clip."""
        script = self._projects.current_script(project_id)
        shots = script["shots"]
        ops = [op for op in (self._valid(self._back(op), shots) for op in ops[:MAX_OPS]) if op]         # checked again: the list came back from the page
        order, texts, done = [s.shot_id for s in shots], {}, []
        for op in ops:
            shot_id = shots[op["line"] - 1].shot_id
            sel = self._projects.selection(shot_id)
            if op["op"] == "swap":
                self._sourcing.swap(shot_id, 0)
            elif op["op"] == "gap":
                self._sourcing.mark_gap(shot_id)
            elif op["op"] == "trim":
                self._sourcing.trim(shot_id, sel.t_in, sel.t_in + op["seconds"])
            elif op["op"] == "speed":
                self._edit.set_shot_options(shot_id, speed=op["value"])
            elif op["op"] == "stabilise":
                self._edit.set_shot_options(shot_id, stabilise=True)
            elif op["op"] == "remove" and shot_id in order and len(order) > 1:
                order.remove(shot_id)
            elif op["op"] == "move" and shot_id in order:
                order.remove(shot_id)
                order.insert(op["to"] - 1, shot_id)
            elif op["op"] == "text":
                texts[shot_id] = op["text"]
            else:
                continue
            done.append(op["describe"])
        new_script = None
        if order != [s.shot_id for s in shots] or texts:
            new_script = self._projects.revise(script["script_id"], order, texts=texts)
        return {"done": done, "script_id": new_script}

    @staticmethod
    def _back(op: dict) -> dict:
        """An operation as the page sent it back, in the words `_valid` reads."""
        names = {"swap": "doi_clip", "gap": "bo_clip", "trim": "cat_ngan", "remove": "bo_cau", "move": "chuyen", "speed": "toc_do", "stabilise": "chong_rung", "text": "sua_loi"}
        return {"loai": names.get(op.get("op"), ""), "cau": op.get("line"), "giay": op.get("seconds"), "den": op.get("to"), "gia_tri": op.get("value"), "loi_moi": op.get("text")}
