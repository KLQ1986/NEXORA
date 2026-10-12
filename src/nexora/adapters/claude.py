"""Text work on Claude through the Anthropic Messages API: writing, critique, checking a line against a source.

It is a cloud model and is given text only: it has no operation that takes a picture, so footage cannot reach it by
this path. Whether any text goes to it at all is the operator's choice, task by task, and privacy mode overrides that
choice. Cost is worked out from the token counts the API reports and the prices in the installation's settings.
"""
import json
import urllib.error
import urllib.request

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result, Usage


def _json_from(text: str) -> dict:
    """The JSON object in an answer, with or without a code fence around it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object")
    return json.loads(text[start:end + 1])


class ClaudeText(Adapter):
    def __init__(self, api_key: str, *, model: str = "claude-haiku-5-5", host: str = "https://api.anthropic.com",
                 input_price: float = 0.0, output_price: float = 0.0, workspace_id: str = ""):
        self._key, self._model, self._host, self._workspace = api_key, model, host.rstrip("/"), workspace_id
        self._prices = (input_price, output_price)              # USD per million tokens, as the operator entered them

    def describe(self) -> Capability:
        return Capability(name="model.claude", operations=("chat",), runs="cloud")

    def environment(self) -> dict:
        return {"model": self._model, "key_present": bool(self._key)}

    def submit(self, request: Request) -> Result:
        body = {"model": self._model, "max_tokens": int(request.params.get("max_tokens", 500)),
                "messages": [{"role": "user", "content": request.params["prompt"] + ("\n\nChỉ trả về một đối tượng JSON, không kèm lời giải thích." if request.params.get("json") else "")}]}
        req = urllib.request.Request(self._host + "/v1/messages", data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json", "x-api-key": self._key, "anthropic-version": "2023-06-01",
                                              **({"anthropic-workspace-id": self._workspace} if self._workspace else {})})
        try:
            with urllib.request.urlopen(req, timeout=request.deadline_seconds or 120) as r:
                out = json.load(r)
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:200]
            code = {400: ErrorCode.INVALID_REQUEST, 401: ErrorCode.AUTH, 403: ErrorCode.AUTH, 404: ErrorCode.INVALID_REQUEST, 413: ErrorCode.INVALID_REQUEST,
                    429: ErrorCode.RATE_LIMITED}.get(err.code, ErrorCode.UNAVAILABLE)
            # Two refusals arrive as plain "bad request" but are nothing the request can fix: only the operator can.
            if "anthropic-workspace-id" in detail:
                raise AdapterError(ErrorCode.AUTH, "this Anthropic key is not tied to a workspace: set anthropic_workspace_id in nexora.toml, or use a key made inside a workspace", retryable=False) from None
            if "credit balance" in detail.lower():
                raise AdapterError(ErrorCode.QUOTA_EXHAUSTED, "the Anthropic account has no credit left: add credit, then try again", retryable=False) from None
            retry = err.headers.get("retry-after") if err.headers else None
            raise AdapterError(code, f"Claude API {err.code}: {detail}", retry_after=float(retry) if retry and retry.replace(".", "", 1).isdigit() else None) from None
        except TimeoutError:
            raise AdapterError(ErrorCode.TIMEOUT, "the Claude API did not answer in time") from None
        except (urllib.error.URLError, ConnectionError) as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"the Claude API is not reachable: {err}") from None
        text = "".join(part.get("text", "") for part in out.get("content", []) if part.get("type") == "text")
        used = out.get("usage") or {}
        tokens_in, tokens_out = int(used.get("input_tokens", 0)), int(used.get("output_tokens", 0))
        usage = Usage(units=tokens_in + tokens_out, cost=round((tokens_in * self._prices[0] + tokens_out * self._prices[1]) / 1e6, 6), measured=bool(used))
        if out.get("stop_reason") == "refusal":
            raise AdapterError(ErrorCode.CONTENT_REJECTED, "Claude declined this request")
        if not request.params.get("json"):
            return Result(outputs={"text": text.strip(), "provider": "claude", "model": self._model}, usage=usage)
        try:
            return Result(outputs={"json": _json_from(text), "provider": "claude", "model": self._model}, usage=usage)
        except ValueError:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"the model did not return JSON: {text[:120]}") from None
