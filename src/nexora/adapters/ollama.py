"""Local models through Ollama: vision description, text reasoning and embeddings. Nothing leaves the machine."""
import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result


class OllamaAdapter(Adapter):
    def __init__(self, *, host: str = "http://127.0.0.1:11434", vision_model: str = "qwen2.5vl:7b", embed_model: str = "bge-m3",
                 judge_model: str = "", writer_model: str = ""):
        self._host, self.vision_model, self.embed_model = host, vision_model, embed_model
        # A model per kind of work, each falling back to the vision model: looking at footage in bulk, judging a candidate, writing.
        self.judge_model, self.writer_model = judge_model or vision_model, writer_model or vision_model

    def describe(self) -> Capability:
        return Capability(name="model", operations=("describe", "chat", "embed"), runs="local")

    def environment(self) -> dict:
        try:
            with urllib.request.urlopen(self._host + "/api/tags", timeout=3) as r:
                installed = [m["name"] for m in json.load(r).get("models", [])]
        except Exception:
            return {"running": False, "models": {m: False for m in dict.fromkeys((self.vision_model, self.judge_model, self.writer_model, self.embed_model))}}
        has = lambda name: any(m == name or m.startswith(name + ":") for m in installed)
        return {"running": True, "models": {m: has(m) for m in dict.fromkeys((self.vision_model, self.judge_model, self.writer_model, self.embed_model))}}

    def _post(self, path: str, body: dict, timeout: float) -> dict:
        req = urllib.request.Request(self._host + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:200]
            code = ErrorCode.INVALID_REQUEST if err.code in (400, 404) else ErrorCode.UNAVAILABLE
            raise AdapterError(code, f"Ollama {err.code}: {detail}") from None
        except TimeoutError:
            raise AdapterError(ErrorCode.TIMEOUT, "the local model did not answer in time") from None
        except (urllib.error.URLError, ConnectionError) as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"Ollama is not reachable: {err}") from None

    def model_for(self, request: Request) -> str:
        if request.operation == "chat":
            return self.writer_model
        return self.judge_model if request.params.get("task") in ("judge", "locate", "focus") else self.vision_model

    def submit(self, request: Request) -> Result:
        timeout = request.deadline_seconds or 300
        if request.operation == "embed":
            out = self._post("/api/embed", {"model": self.embed_model, "input": request.inputs["texts"]}, timeout)
            return Result(outputs={"vectors": out["embeddings"]})
        message = {"role": "user", "content": request.params["prompt"]}
        if request.operation == "describe":
            paths = [Path(p) for p in request.inputs["images"]]
            missing = [p for p in paths if not p.is_file()]
            if missing:
                raise AdapterError(ErrorCode.MISSING_INPUT, f"{missing[0]} does not exist")
            message["images"] = [base64.b64encode(p.read_bytes()).decode() for p in paths]
        want_json = request.operation == "describe" or request.params.get("json")
        body = {"model": self.model_for(request), "stream": False, "messages": [message],
                "options": {"temperature": 0.1, "num_predict": int(request.params.get("max_tokens", 500)), "num_ctx": 8192}}
        if want_json:
            body["format"] = "json"
        text = self._post("/api/chat", body, timeout)["message"].get("content", "")
        if not want_json:
            return Result(outputs={"text": text.strip()})
        try:
            return Result(outputs={"json": json.loads(text)})
        except json.JSONDecodeError:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"the model did not return JSON: {text[:120]}") from None
