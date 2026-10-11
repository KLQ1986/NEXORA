"""Notifications in the macOS Notification Centre, so that the operator need not watch the screen."""
import json

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.process import run_process


class DesktopNotifier(Adapter):
    def describe(self) -> Capability:
        return Capability(name="desktop", operations=("notify",), runs="local")

    def submit(self, request: Request) -> Result:
        # json.dumps yields a quoted string that AppleScript reads as written, including Vietnamese and quotation marks.
        text, title = (json.dumps(str(request.inputs[k]), ensure_ascii=False) for k in ("text", "title"))
        done = run_process(["osascript", "-e", f"display notification {text} with title {title}"], timeout=10)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"osascript failed: {done.stderr.strip()[:200]}")
        return Result()
