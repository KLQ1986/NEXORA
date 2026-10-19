"""What a licence string allows, for material NEXORA publishes (research 2026-10-19, OpenMontage stock and rights).

The stock libraries hand back licence strings of every shape: a library's own licence, a Creative Commons URL, Wikimedia's
short name, or a hedge such as "Public Domain / CC (archive.org — verify per item)". OpenMontage records them and never
looks at them; of 33 clips NEXORA fetched through it, two forbade commercial use and 24 had no licence on record. Each string
is sorted here into one class that says what may be done with it on a channel that may earn money:

- `free`: public domain, CC0, or a library licence that allows commercial use without credit (Pexels, Pixabay, ...);
- `attribution`: allowed with a credit (CC BY);
- `share_alike`: allowed with a credit, but a video made from it must carry the same licence (CC BY-SA): not for a normal upload;
- `restricted`: not allowed (non-commercial, no derivatives, educational use only);
- `unknown`: nothing on record says what is allowed ("verify per item", "check individual licence", empty).
"""
from __future__ import annotations

import re

CLASSES = ("free", "attribution", "share_alike", "restricted", "unknown")
LABELS = {"free": "Tự do", "attribution": "Cần ghi công", "share_alike": "Share-alike", "restricted": "Cấm dùng thương mại", "unknown": "Chưa rõ giấy phép"}
SAFE = frozenset({"free", "attribution"})                   # what may be taken without the operator saying why

_RESTRICTED = re.compile(r"(\bby-nc\b|by-nc-|\bnc\b|non-?commercial|noncommercial|\bnd\b|-nd\b|/nd/|no-?deriv|noderiv|educational|"
                         r"editorial use only|personal use only)", re.I)
_SHARE_ALIKE = re.compile(r"(by-sa|\bsa\b|share-?alike|sharealike)", re.I)
_HEDGED = re.compile(r"(verify|check individual|varies|unknown|not specified|see source|all rights reserved)", re.I)
_FREE = re.compile(r"(public ?domain|publicdomain|\bpd\b|\bcc0\b|zero/1\.0|mark/1\.0|pexels license|pixabay (content )?license|"
                   r"coverr license|mixkit license|u\.s\. federal government|no attribution required|user-provided)", re.I)
_ATTRIBUTION = re.compile(r"(\bcc[ -]?by\b|licenses/by/|attribution)", re.I)


def classify(licence: str | None) -> str:
    """The class of one licence string (see the module docstring)."""
    text = (licence or "").strip()
    if not text:
        return "unknown"
    if _RESTRICTED.search(text):
        return "restricted"
    if _SHARE_ALIKE.search(text):
        return "share_alike"
    if _HEDGED.search(text):
        return "unknown"
    if _FREE.search(text):
        return "free"
    if _ATTRIBUTION.search(text):
        return "attribution"
    return "unknown"


def why_not(cls: str) -> str | None:
    """Why material of this class should not go out as it stands; None when it may."""
    return {"restricted": "giấy phép cấm dùng thương mại hoặc cấm chỉnh sửa",
            "share_alike": "giấy phép share-alike buộc cả video phải mang cùng giấy phép",
            "unknown": "không có giấy phép rõ ràng trong hồ sơ"}.get(cls)
