"""Running local tools as child processes with a time limit and captured output."""
import subprocess
from dataclasses import dataclass

from nexora.core.adapter import AdapterError, ErrorCode


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str


def run_process(cmd: list[str], *, timeout: float, cwd: str | None = None, stdin: str | None = None) -> Completed:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, input=stdin)
    except subprocess.TimeoutExpired:           # subprocess.run has already killed the child
        raise AdapterError(ErrorCode.TIMEOUT, f"{cmd[0]} exceeded {timeout:g}s") from None
    except FileNotFoundError:
        raise AdapterError(ErrorCode.UNAVAILABLE, f"{cmd[0]} is not installed", retryable=False) from None
    return Completed(done.returncode, done.stdout, done.stderr)
