"""Settings of one installation, read from `nexora.toml`. Every value has a default, so the file is optional."""
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: str = "data"
    port: int = 8600
    ollama_host: str = "http://127.0.0.1:11434"
    vision_model: str = "qwen3-vl:8b-instruct"
    embed_model: str = "bge-m3"
    picture_model: str = "google/siglip2-base-patch16-256"
    judge_model: str = ""
    writer_model: str = ""
    voice: str = "Linh"
    match_threshold: float = 0.52
    segment_seconds: float = 15.0
    judge: bool = True
    openmontage_repo: str = "~/openmontage"
    min_free_gb: float = 2.0
    backups_kept: int = 7
    speech_model: str = "data/models/ggml-large-v3-turbo-q5_0.bin"
    speech_language: str = "vi"
    speech_vad_model: str = "data/models/ggml-silero-v5.1.2.bin"
    pollinations: bool = True
    pollinations_token: str = ""
    publish_folder: str = "~/Movies/NEXORA"
    ffmpeg_binary: str = ""
    runpod_api_key: str = ""
    runpod_video_endpoint: str = ""
    runpod_price_per_second: float = 0.0
    runpod_lipsync_endpoint: str = ""
    runpod_upscale_endpoint: str = ""
    runpod_restore_endpoint: str = ""
    runpod_train_endpoint: str = ""
    runpod_image_endpoint: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_privacy: str = "private"
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""
    claude_model: str = "claude-haiku-5-5"
    claude_input_price: float = 0.0
    claude_output_price: float = 0.0

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
vision_model = "qwen3-vl:8b-instruct"     # sees frames: describes footage, judges candidates, finds the subject
embed_model = "bge-m3"            # turns text into vectors for search
picture_model = "google/siglip2-base-patch16-256"   # finds what is in the picture; set up with scripts/setup-pictures.sh, empty turns it off
judge_model = ""                  # judges candidates and finds the subject; empty means the vision model
writer_model = ""                 # drafts scripts and search words; empty means the vision model
voice = "Linh"                    # a voice of the macOS `say` command
match_threshold = 0.52            # how alike a moment must be to a script line to be considered (0 to 1)
segment_seconds = 15.0            # the longest stretch of footage described as one moment; footage is divided where its content changes
judge = true                      # let the vision model look at candidate frames before a clip is proposed
openmontage_repo = "~/openmontage"
min_free_gb = 2.0                 # below this much free disk, work that writes large files waits for the operator
backups_kept = 7                  # how many database backups to keep
speech_model = "data/models/ggml-large-v3-turbo-q5_0.bin"   # a whisper.cpp model; empty turns speech recognition off
speech_language = "vi"            # the language spoken in the footage
speech_vad_model = "data/models/ggml-silero-v5.1.2.bin"   # a voice detector for whisper.cpp: only stretches with a voice are transcribed
pollinations = true               # stills from Pollinations (only the prompt leaves this machine); without a token only a few stills at a time
pollinations_token = ""           # a token from a Pollinations account lifts that limit
publish_folder = "~/Movies/NEXORA"   # where "publish to folder" puts finished packages; empty turns it off
runpod_api_key = ""               # with an endpoint id, turns on video from a model on your RunPod serverless endpoint; RUNPOD_API_KEY does the same
runpod_video_endpoint = ""        # the id of the endpoint; its handler gets prompt, image (base64), seconds, seed, aspect and returns video_url or video
runpod_lipsync_endpoint = ""      # an endpoint running a lip-sync model: gets video and audio (base64), returns video_url or video
runpod_image_endpoint = ""        # an endpoint running an image model: gets prompt, seed, aspect, references, loras; returns image_url or image
runpod_train_endpoint = ""        # an endpoint that trains a character model: gets images (base64), name, trigger; returns model_url or model
runpod_upscale_endpoint = ""      # an endpoint running an upscaling model: gets video (base64) and scale, returns video_url or video
runpod_restore_endpoint = ""      # an endpoint running VRT/RVRT for Visual Quality: gets video (base64) and task "deblur", returns video_url or video
runpod_price_per_second = 0.0     # USD per second of GPU time on that endpoint, for the cost record
ffmpeg_binary = ""                # empty: a fuller build (brew install ffmpeg-full) if installed, else the ffmpeg on the path. HDR footage needs the fuller build
youtube_client_id = ""            # an OAuth client of your own Google Cloud project, with the YouTube Data API enabled
youtube_client_secret = ""
youtube_refresh_token = ""        # a refresh token for your channel with the scopes youtube.upload and youtube.readonly; all three turn on publishing to YouTube
youtube_privacy = "private"       # private, unlisted or public: how an uploaded video starts out
anthropic_api_key = ""            # a key turns on Claude for text work; the ANTHROPIC_API_KEY environment variable does the same. Footage is never sent
anthropic_workspace_id = ""       # needed only for a key that is not tied to one workspace
claude_model = "claude-haiku-5-5"
claude_input_price = 0.0          # USD per million input tokens, for the cost record; take the figure from your Anthropic price list
claude_output_price = 0.0         # USD per million output tokens
"""
