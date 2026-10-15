"""The analyzers of the Video Intelligence domain, as declared to the canonical model."""
from nexora.core.intelligence import Analyzer

# The analyzers of this domain, with what each needs (design 2026-10-15, section 3.1). A version change marks every recording
# analysed with the older version, and every analyzer that needs it, as stale (`VideoIntelligence.stale`).
ANALYZERS = (
    Analyzer("structure", "2", ("file",), ("shot", "beat", "camera", "shake", "sharpness", "exposure", "speech", "speed", "still", "direction", "position")),
    Analyzer("telemetry", "1", ("file",), ("angle", "tilt", "turning", "exposure_settings")),
    Analyzer("look", "4", ("file", "structure"), ("people", "shot_size", "posture", "place", "scene_tags", "horizon", "aesthetic", "subject_place", "speaker",
                                                  "light", "backlit", "colour", "noise", "composition", "depth", "text", "holding", "span")),
    Analyzer("listen", "1", ("file",), ("sound", "music", "loudness", "clipping", "wind")),
    Analyzer("speech", "2", ("file", "listen"), ("sentence", "speaker_id")),
    Analyzer("describe", "v4", ("look", "structure", "speech"), ("description", "model.shot_size", "model.people", "model.place", "model.angle")),
    Analyzer("events", "1", ("describe",), ("event",)),
    Analyzer("scenes", "1", ("look",), ("scene",)),
    Analyzer("pictures", "1", ("file",), ("pictures",)),          # frames as SigLIP 2 vectors, for search by what is in the picture
)
BY_NAME = {a.name: a for a in ANALYZERS}
