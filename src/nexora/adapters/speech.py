"""Speech to text with a time for every word, through whisper.cpp running on this machine. Nothing is sent anywhere."""
import json
import shutil
import tempfile
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.process import run_process


class WhisperCpp(Adapter):
    def __init__(self, model_path: str | Path, *, language: str = "vi", binary: str = "whisper-cli"):
        self._model, self._language, self._binary = Path(model_path).expanduser(), language, binary

    def describe(self) -> Capability:
        return Capability(name="speech", operations=("transcribe",), runs="local")

    def environment(self) -> dict:
        return {"binary": shutil.which(self._binary), "model": str(self._model), "model_present": self._model.is_file(), "language": self._language}

    def submit(self, request: Request) -> Result:
        source = Path(request.inputs["path"])
        if not source.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{source} does not exist")
        if not self._model.is_file():
            raise AdapterError(ErrorCode.UNAVAILABLE, f"the speech model {self._model} is not on this machine", retryable=False)
        timeout = request.deadline_seconds or 3600
        with tempfile.TemporaryDirectory() as work:
            wav, out = Path(work) / "audio.wav", Path(work) / "words"
            made = run_process(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-ar", "16000", "-ac", "1", str(wav)], timeout=timeout)
            if made.returncode != 0 or not wav.is_file():
                raise AdapterError(ErrorCode.INVALID_REQUEST, f"no sound could be read from {source.name}: {made.stderr.strip()[:160]}")
            # One word per segment (-ml 1 with -sow), so that every word carries its own start and end.
            done = run_process([self._binary, "-m", str(self._model), "-l", str(request.params.get("language") or self._language), "-ojf", "-of", str(out),
                                "-ml", "1", "-sow", "-np", str(wav)], timeout=timeout)
            if done.returncode != 0 or not out.with_suffix(".json").is_file():
                raise AdapterError(ErrorCode.UNAVAILABLE, f"whisper-cli failed: {done.stderr.strip()[-200:]}")
            raw = json.loads(out.with_suffix(".json").read_text(encoding="utf-8", errors="replace"))
        words = []
        for item in raw.get("transcription", []):
            text = item.get("text", "").strip()
            if not text or text.startswith("["):                       # markers such as [_BEG_] and [BLANK_AUDIO] are not speech
                continue
            sure = min((t.get("p", 1.0) for t in item.get("tokens", []) if not t.get("text", "").startswith("[_")), default=1.0)
            words.append({"text": text, "start": item["offsets"]["from"] / 1000, "end": item["offsets"]["to"] / 1000, "p": round(float(sure), 3)})
        return Result(outputs={"words": words, "language": raw.get("result", {}).get("language", self._language)})
