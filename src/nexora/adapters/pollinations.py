"""Stills from Pollinations, an image service that needs no account or key.

Only the prompt and the seed leave this machine, never footage. It is a cloud tool, so privacy mode refuses it.
The service takes no reference pictures: consistency rests on the wording of the prompt alone.

Without an account the service gives only a few pictures before it answers 402 for a while (measured 2026-10-12: one
to three pictures, then refusals for a minute or more). That is reported as an exhausted allowance, so the run waits
for the operator and keeps the stills it already has. A token from an account, when given, is sent with each request.
"""
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result, Usage

SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}


class PollinationsImage(Adapter):
    def __init__(self, *, host: str = "https://image.pollinations.ai", model: str = "", token: str = ""):
        self._host, self._model, self._token = host.rstrip("/"), model, token

    def describe(self) -> Capability:
        return Capability(name="image_gen.pollinations", operations=("generate",), runs="cloud")

    def submit(self, request: Request) -> Result:
        width, height = SIZES.get(request.params.get("aspect", "16:9"), SIZES["16:9"])
        query = urllib.parse.urlencode({"width": width, "height": height, "seed": int(request.params.get("seed", 0)) % 2**31, "nologo": "true", **({"model": self._model} if self._model else {})})
        headers = {"user-agent": "NEXORA", **({"authorization": f"Bearer {self._token}"} if self._token else {})}
        url = f"{self._host}/prompt/{urllib.parse.quote(request.inputs['prompt'][:1500], safe='')}?{query}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=request.deadline_seconds or 120) as r:
                kind, data = r.headers.get_content_type(), r.read(30_000_000)
        except urllib.error.HTTPError as err:
            if err.code == 402:
                raise AdapterError(ErrorCode.QUOTA_EXHAUSTED, "the free allowance of Pollinations is used up for now; try again later or set pollinations_token") from None
            if err.code in (401, 403):
                raise AdapterError(ErrorCode.AUTH, "Pollinations refused the token") from None
            code = ErrorCode.RATE_LIMITED if err.code == 429 else ErrorCode.CONTENT_REJECTED if err.code == 400 else ErrorCode.UNAVAILABLE
            raise AdapterError(code, f"Pollinations answered {err.code}", retry_after=30 if err.code == 429 else None) from None
        except TimeoutError:
            raise AdapterError(ErrorCode.TIMEOUT, "Pollinations did not answer in time") from None
        except (urllib.error.URLError, ConnectionError) as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"Pollinations is not reachable: {err}") from None
        if not kind.startswith("image/") or len(data) < 1000:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"Pollinations returned {kind}, not a picture")
        out = Path(request.params["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        if kind == "image/png" and out.suffix == ".png":
            out.write_bytes(data)
        else:                                            # the caller names the file; the picture is rewritten in that format
            import io
            from PIL import Image
            Image.open(io.BytesIO(data)).convert("RGB").save(out)
        return Result(outputs={"provider": "pollinations", "model": self._model or "default"}, files=(str(out),), usage=Usage(units=1, cost=0.0))
