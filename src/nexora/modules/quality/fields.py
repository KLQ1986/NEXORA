"""How right each field of the footage profile is, and whether it may be used (design 2026-10-14, section 8).

The operator says what is true of a stretch of footage: how tight the frame is, how many people are in it, whether it is
indoors, whether text is on screen. Those answers are the golden labels. Measuring a field compares what the system holds
for each labelled stretch with the label. A field is used by matching and by search filters only once it has been right
often enough on enough labels ("released"); until then it is shown but not relied on ("trial"); a released field that falls
below its bar at a later measurement is withdrawn ("withdrawn") until it is good again.

Confidence is checked too: of the values the system called "high", how many were right. If fewer than the bar, the field's
"high" is not worth its name and the report says so.
"""
import json
import time
from pathlib import Path
from typing import Callable

from nexora.core import db
from nexora.core.ids import new_id
from nexora.core.index import MomentIndex

SCHEMA = """
CREATE TABLE IF NOT EXISTS golden_labels (label_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, t_start REAL NOT NULL, t_end REAL NOT NULL, field TEXT NOT NULL,
    value TEXT NOT NULL, labelled_by TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE (asset_id, t_start, t_end, field));
CREATE TABLE IF NOT EXISTS field_runs (run_id TEXT PRIMARY KEY, created_at REAL NOT NULL, config TEXT NOT NULL, results TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS field_status (field TEXT PRIMARY KEY, status TEXT NOT NULL, accuracy REAL, labels INTEGER NOT NULL, changed_at REAL NOT NULL);
"""
MIN_LABELS = 10          # a field is not released on fewer labels than this, however right it was
MIN_COVERAGE = 0.8       # nor if it gave no value for more than a fifth of the labelled stretches: silence on the hard cases is not accuracy
HIGH_MUST_BE = 0.95      # "high" confidence must be right at least this often
MEDIUM_MUST_BE = 0.75
SIZES = ("cực toàn", "toàn", "trung", "cận", "đặc tả")


def _profile(name):
    return lambda data: ((data.get("profile") or {}).get(name) or {})


def _model(name):
    return lambda data: ((data.get("model_labels") or {}).get(name) or {})


def _measured(name):
    return lambda data: ((data.get("labels") or {}).get(name) or {})


def _text_present(data):
    found = (data.get("profile") or {}).get("text")
    if not data.get("profile"):
        return {}
    return {"value": "có" if found and found.get("value") else "không", "confidence": (found or {}).get("confidence", "medium")}


# Each field: where its value is read, the values it may take, the bar it must clear to be released, and its source.
FIELDS: dict[str, dict] = {
    "shot_size": {"name": "Cỡ cảnh (đo)", "read": _profile("shot_size"), "values": SIZES, "bar": 0.90, "source": "measured"},
    "people": {"name": "Số người (nhận diện)", "read": _profile("people"), "values": ("không", "một", "hai", "nhóm", "đám đông"), "bar": 0.90, "source": "recognized"},
    "place": {"name": "Trong nhà hay ngoài trời (nhận diện)", "read": _profile("place"), "values": ("trong nhà", "ngoài trời"), "bar": 0.90, "source": "recognized"},
    "text_present": {"name": "Có chữ trên hình (nhận diện)", "read": _text_present, "values": ("có", "không"), "bar": 0.90, "source": "recognized"},
    "speaker": {"name": "Người nói ở trong khung (đo)", "read": _profile("speaker"), "values": ("trong khung", "ngoài khung"), "bar": 0.90, "source": "measured"},
    "camera": {"name": "Chuyển động máy (đo)", "read": _measured("camera"), "values": ("static", "pan", "tilt", "push_in", "pull_out", "handheld"), "bar": 0.95, "source": "measured"},
    # What a model says is measured against the same answers as the measured field it shadows.
    "model.co_canh": {"name": "Cỡ cảnh (mô hình)", "read": _model("co_canh"), "values": SIZES, "bar": 0.85, "source": "model", "truth": "shot_size"},
    "model.so_nguoi": {"name": "Số người (mô hình)", "read": _model("so_nguoi"), "values": ("không", "một", "hai", "nhóm", "đám đông"), "bar": 0.85, "source": "model", "truth": "people"},
    "model.noi_chon": {"name": "Trong nhà hay ngoài trời (mô hình)", "read": _model("noi_chon"), "values": ("trong nhà", "ngoài trời"), "bar": 0.85, "source": "model", "truth": "place"},
}


def compare(field: str, held, truth: str) -> bool:
    return str(held) == str(truth)


class Fields:
    def __init__(self, db_path: str | Path, index: MomentIndex):
        self._db, self._index = db.LocalConnections(db_path), index
        with db.write(self._conn) as c:
            for statement in SCHEMA.strip().split(";\n"):
                c.execute(statement)

    @property
    def _conn(self):
        return self._db.get()

    # ------------------------------------------------------------------------------------------------- golden labels
    def label(self, asset_id: str, t_start: float, t_end: float, field: str, value: str, *, by: str = "operator") -> str:
        if field not in FIELDS or FIELDS[field].get("truth"):
            raise ValueError(f"unknown field {field}")
        if value not in FIELDS[field]["values"]:
            raise ValueError(f"{value} is not a value of {field}")
        with db.write(self._conn) as c:
            row = c.execute("SELECT label_id FROM golden_labels WHERE asset_id = ? AND t_start = ? AND t_end = ? AND field = ?",
                            (asset_id, round(t_start, 2), round(t_end, 2), field)).fetchone()
            label_id = row[0] if row else new_id("gld")
            c.execute("INSERT INTO golden_labels (label_id, asset_id, t_start, t_end, field, value, labelled_by, created_at) VALUES (?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(label_id) DO UPDATE SET value = excluded.value, labelled_by = excluded.labelled_by, created_at = excluded.created_at",
                      (label_id, asset_id, round(t_start, 2), round(t_end, 2), field, value, by, time.time()))
        return label_id

    def unlabel(self, label_id: str) -> None:
        with db.write(self._conn) as c:
            c.execute("DELETE FROM golden_labels WHERE label_id = ?", (label_id,))

    def labels(self, asset_id: str | None = None) -> list[dict]:
        if asset_id:
            rows = self._conn.execute("SELECT * FROM golden_labels WHERE asset_id = ? ORDER BY t_start, field", (asset_id,))
        else:
            rows = self._conn.execute("SELECT * FROM golden_labels ORDER BY asset_id, t_start, field")
        return [dict(r) for r in rows]

    def forget_asset(self, asset_id: str) -> int:
        with db.write(self._conn) as c:
            return c.execute("DELETE FROM golden_labels WHERE asset_id = ?", (asset_id,)).rowcount

    # ------------------------------------------------------------------------------------------------------ measuring
    def _held(self, label: dict) -> tuple[dict | None, dict]:
        """The beat a label is about (the one holding the middle of the labelled stretch) and the field's value there."""
        middle = (label["t_start"] + label["t_end"]) / 2
        beat = next((m for m in self._index.moments(label["asset_id"], level="segment") if m.t_start <= middle < m.t_end or m.t_start == m.t_end == middle), None)
        if beat is None:
            return None, {}
        return beat, FIELDS[label["field"]]["read"](beat.data) or {}

    def measure(self, config: dict | None = None) -> dict:
        """Compare every field with every label; set each field's status; keep the run with the configuration it was made under."""
        results: dict[str, dict] = {}
        for field, spec in FIELDS.items():
            labels = [{**l, "field": field} for l in self.labels() if l["field"] == spec.get("truth", field)]
            right = wrong = missing = 0
            by_conf: dict[str, list[int]] = {}
            mistakes, confusion = [], {}
            for label in labels:
                beat, held = self._held(label)
                if not held or held.get("value") in (None, ""):
                    missing += 1
                    continue
                ok = compare(field, held["value"], label["value"])
                right += ok
                wrong += not ok
                conf = held.get("confidence", "medium")
                by_conf.setdefault(conf, [0, 0])[0 if ok else 1] += 1
                key = f"{label['value']} → {held['value']}"
                confusion[key] = confusion.get(key, 0) + 1
                if not ok and len(mistakes) < 20:
                    mistakes.append({"asset_id": label["asset_id"], "t_start": label["t_start"], "t_end": label["t_end"], "truth": label["value"], "held": held["value"],
                                     "confidence": conf})
            answered = right + wrong
            accuracy = round(right / answered, 3) if answered else None
            calibration = {c: {"right": v[0], "wrong": v[1], "share": round(v[0] / (v[0] + v[1]), 3)} for c, v in by_conf.items()}
            calibrated = all(calibration[c]["share"] >= bar for c, bar in (("high", HIGH_MUST_BE), ("medium", MEDIUM_MUST_BE)) if c in calibration and
                             calibration[c]["right"] + calibration[c]["wrong"] >= 5)
            coverage = round(answered / len(labels), 3) if labels else None
            near = None
            if field in ("shot_size", "model.co_canh") and answered:
                near = round(sum(1 for l in labels for _, h in [self._held(l)] if h.get("value") in SIZES and abs(SIZES.index(h["value"]) - SIZES.index(l["value"])) <= 1)
                             / answered, 3)
            results[field] = {"name": spec["name"], "source": spec["source"], "bar": spec["bar"], "labels": len(labels), "answered": answered, "missing": missing, "coverage": coverage,
                              "accuracy": accuracy, "within_one": near, "calibration": calibration, "calibrated": calibrated,
                              "confusion": dict(sorted(confusion.items(), key=lambda kv: -kv[1])), "mistakes": mistakes,
                              "status": self._decide(field, accuracy, answered, spec["bar"], coverage)}
        run_id = new_id("fld")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO field_runs (run_id, created_at, config, results) VALUES (?,?,?,?)",
                      (run_id, time.time(), json.dumps(config or {}, ensure_ascii=False), json.dumps(results, ensure_ascii=False)))
        return {"run_id": run_id, "fields": results}

    def _decide(self, field: str, accuracy: float | None, answered: int, bar: float, coverage: float | None = 1.0) -> str:
        before = self.status(field)
        if accuracy is not None and answered >= MIN_LABELS and accuracy >= bar and (coverage or 0) >= MIN_COVERAGE:
            status = "released"
        elif before == "released" or (before == "withdrawn" and (accuracy is None or accuracy < bar)):
            status = "withdrawn"
        else:
            status = "trial"
        with db.write(self._conn) as c:
            c.execute("INSERT INTO field_status (field, status, accuracy, labels, changed_at) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(field) DO UPDATE SET status = excluded.status, accuracy = excluded.accuracy, labels = excluded.labels, changed_at = excluded.changed_at",
                      (field, status, accuracy, answered, time.time()))
        return status

    def status(self, field: str) -> str:
        row = self._conn.execute("SELECT status FROM field_status WHERE field = ?", (field,)).fetchone()
        return row[0] if row else "trial"

    def released(self) -> set[str]:
        return {r[0] for r in self._conn.execute("SELECT field FROM field_status WHERE status = 'released'")}

    def runs(self, limit: int = 20) -> list[dict]:
        return [{"run_id": r["run_id"], "created_at": r["created_at"], "config": json.loads(r["config"]), "results": json.loads(r["results"])}
                for r in self._conn.execute("SELECT * FROM field_runs ORDER BY created_at DESC LIMIT ?", (limit,))]

    def regressions(self, worse_by: float = 0.03) -> list[dict]:
        """Released fields whose accuracy fell by more than `worse_by` between the last two runs (design section 8.6)."""
        runs = self.runs(2)
        if len(runs) < 2:
            return []
        now, before = runs[0]["results"], runs[1]["results"]
        out = []
        for field, result in now.items():
            was = (before.get(field) or {}).get("accuracy")
            if was is not None and result.get("accuracy") is not None and was - result["accuracy"] > worse_by and (before[field].get("status") == "released"):
                out.append({"field": field, "before": was, "now": result["accuracy"]})
        return out
