"""Settings of one installation, read from `nexora.toml`. Every value has a default, so the file is optional."""
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: str = "data"
    port: int = 8600
    ollama_host: str = "http://127.0.0.1:11434"
    vision_model: str = "qwen2.5vl:7b"
    embed_model: str = "bge-m3"
    judge_model: str = ""
    writer_model: str = ""
    voice: str = "Linh"
    match_threshold: float = 0.52
    segment_seconds: float = 12.0
    judge: bool = True
    openmontage_repo: str = "~/openmontage"
    min_free_gb: float = 2.0
    backups_kept: int = 7

    @classmethod
    def load(cls, path: str | Path = "nexora.toml") -> "Config":
        path = Path(path)
        if not path.is_file():
            return cls()
        given = tomllib.loads(path.read_text(encoding="utf-8"))
        known = {f.name: f.type for f in fields(cls)}
        unknown = sorted(set(given) - set(known))
        if unknown:
            raise ValueError(f"{path}: unknown settings {unknown}; known settings are {sorted(known)}")
        return cls(**given)


TEMPLATE = """# NEXORA settings. Delete a line to fall back to its default.
data_dir = "data"                 # database, managed media, backups, logs
port = 8600                       # the Web UI and API listen on 127.0.0.1 at this port
ollama_host = "http://127.0.0.1:11434"
vision_model = "qwen2.5vl:7b"     # sees frames: describes footage, judges candidates, finds the subject
embed_model = "bge-m3"            # turns text into vectors for search
judge_model = ""                  # judges candidates and finds the subject; empty means the vision model
writer_model = ""                 # drafts scripts and search words; empty means the vision model
voice = "Linh"                    # a voice of the macOS `say` command
match_threshold = 0.52            # how alike a moment must be to a script line to be considered (0 to 1)
segment_seconds = 12.0            # the length of footage described as one moment
judge = true                      # let the vision model look at candidate frames before a clip is proposed
openmontage_repo = "~/openmontage"
min_free_gb = 2.0                 # below this much free disk, work that writes large files waits for the operator
backups_kept = 7                  # how many database backups to keep
"""
