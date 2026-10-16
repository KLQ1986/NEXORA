"""The register of colour encodings Visual Quality can read and turn into Rec.709 (design 2026-10-16 §3.1, ColorRegistry).

An entry says how to recognise an encoding (the camera that made the file, what the file declares, what its picture looks
like) and how to transform it: a maker's LUT (`lut`, a file in the LUT folder, with where to fetch it), an OpenColorIO
colour space baked into a LUT (`ocio`), or HDR tone mapping (`tonemap`). An encoding is taken only when what was measured
agrees with it: a file that says it is Rec.709 but looks flat is reported, and a flat file from an unknown camera is called
"probably log, encoding unknown" rather than given a guessed curve.
"""
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Encoding:
    key: str
    name: str
    transform: str                         # "lut", "ocio", "tonemap", "none"
    source: str = ""                       # LUT file name, OCIO colour space, or tone map curve
    fetch: str = ""                        # where a maker's LUT is published
    device: str = ""                       # pattern on the camera/encoder that made the file
    transfer: tuple[str, ...] = ()         # declared transfer functions it comes with
    log_look: bool = False                 # does it look flat (log) before transform
    notes: str = ""


DJI_CDN = "https://terra-1-g.djicdn.com/851d20f7b9f64838a34cd02351370894"

ENCODINGS = [
    # DJI D-Log M: a flattened Rec.709 whose curve DJI does not publish; each camera has its own LUT. The files are tagged
    # bt709, so they are told by the camera and by how flat they look.
    Encoding("dji_osmo_action6_dlogm", "DJI Osmo Action 6 D-Log M", "lut", "dji_osmo_action6_dlogm_to_rec709.cube",
             f"{DJI_CDN}/AC206%20LUT/DJI%20OSMO%20Action%206%20D-LogM%20to%20Rec.709%20LUT-11.17.cube", device=r"osmo\s*action\s*6|osmoaction6", log_look=True),
    Encoding("dji_mini4pro_dlogm", "DJI Mini 4 Pro D-Log M", "lut", "dji_mini4pro_dlogm_to_rec709.cube",
             f"{DJI_CDN}/140%20lut/DJI%20Mini%204%20Pro%20D-Log%20M%20to%20Rec.709%20V1_.cube", device=r"mini\s*4\s*pro|fc8482", log_look=True),
    Encoding("dji_air3s_dlogm", "DJI Air 3S D-Log M", "lut", "dji_air3s_dlogm_to_rec709.cube",
             f"{DJI_CDN}/234_lut/DJI%20Air%203S%20%20D-Log%20M%20to%20Rec.709%20V1_.cube", device=r"air\s*3s", log_look=True),
    Encoding("dji_flip_dlogm", "DJI Flip D-Log M", "lut", "dji_flip_dlogm_to_rec709.cube",
             f"{DJI_CDN}/141%20LUT/DJI%20Flip%20D-Log%20M%20to%20Rec.709%20V1_.cube", device=r"\bflip\b", log_look=True),
    Encoding("dji_pocket4p_dlog", "DJI Osmo Pocket 4P D-Log", "lut", "dji_pocket4p_dlog_to_rec709.cube",
             f"{DJI_CDN}/HG224%20LUT/DJI%20OSMO%20Pocket%204P%20D-Log%20to%20Rec.709%20V2.0%20size33.cube", device=r"pocket\s*4", log_look=True),
    # Encodings OpenColorIO knows (studio config, ACES 2): told by the camera or by a declared transfer.
    Encoding("apple_log", "Apple Log (iPhone Pro)", "ocio", "Apple Log", device=r"iphone", log_look=True,
             notes="iPhone 15 Pro and later; files carry the Apple Log tag"),
    Encoding("apple_log2", "Apple Log 2", "ocio", "Apple Log 2", device=r"iphone 17", log_look=True),
    Encoding("sony_slog3_cine", "Sony S-Log3 S-Gamut3.Cine", "ocio", "S-Log3 S-Gamut3.Cine", device=r"sony|ilce|ilme|fx\d|a7s|zv-e", log_look=True),
    Encoding("canon_clog3", "Canon Log 3", "ocio", "CanonLog3 CinemaGamut D55", device=r"canon|eos", log_look=True),
    Encoding("canon_clog2", "Canon Log 2", "ocio", "CanonLog2 CinemaGamut D55", device=r"canon c\d|cinema eos", log_look=True),
    Encoding("panasonic_vlog", "Panasonic V-Log", "ocio", "V-Log V-Gamut", device=r"panasonic|lumix|dc-g|dc-s", log_look=True),
    Encoding("arri_logc4", "ARRI LogC4", "ocio", "ARRI LogC4", device=r"alexa 35", log_look=True),
    Encoding("arri_logc3", "ARRI LogC3", "ocio", "ARRI LogC3 (EI800)", device=r"arri|alexa", log_look=True),
    Encoding("red_log3g10", "RED Log3G10", "ocio", "Log3G10 REDWideGamutRGB", device=r"\bred\b|komodo|v-raptor", log_look=True),
    Encoding("bmd_film5", "Blackmagic Film Gen 5", "ocio", "BMDFilm WideGamut Gen5", device=r"blackmagic|bmpcc|ursa", log_look=True),
    Encoding("dji_dlog", "DJI D-Log (D-Gamut)", "ocio", "D-Log D-Gamut", device=r"zenmuse|inspire|ronin 4d", log_look=True),
    # HDR: told by the declared transfer, tone mapped to SDR.
    Encoding("hdr_pq", "HDR10 / PQ", "tonemap", "hable", transfer=("smpte2084",)),
    Encoding("hdr_hlg", "HLG", "tonemap", "hable", transfer=("arib-std-b67",), notes="iPhone records HLG with Dolby Vision metadata"),
    Encoding("rec709", "Rec.709 (already for display)", "none", transfer=("bt709", "smpte170m", "bt470bg", "iec61966-2-1", "")),
]
BY_KEY = {e.key: e for e in ENCODINGS}

# What a flat (log) picture measures: little contrast and little colour, before any transform.
LOG_CONTRAST, LOG_SATURATION = 0.42, 0.16


@dataclass
class Match:
    encoding: Encoding | None
    confidence: str                         # "high", "medium", "low"
    why: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def looks_log(contrast: float, saturation: float, *, depth: int) -> bool:
    """Ungraded log: low contrast and low colour together, on a source with enough bits to be graded."""
    return (depth >= 10 and contrast < LOG_CONTRAST and saturation < LOG_SATURATION) or (contrast < 0.32 and saturation < 0.1)


def identify(technical: dict, *, contrast: float, saturation: float) -> Match:
    """The encoding of a source from what it declares and how it looks; never a guess presented as a finding."""
    device = " ".join(str(technical.get(k) or "") for k in ("device", "encoder", "make", "model")).lower()
    transfer = str(technical.get("color_transfer") or "")
    depth = int(technical.get("bit_depth") or 8)
    flat = looks_log(contrast, saturation, depth=depth)
    why = [f"máy: {device.strip() or 'không rõ'}", f"thẻ transfer: {transfer or 'không có'}",
           f"tương phản {contrast:.2f}, bão hoà {saturation:.2f}" + (" (phẳng như log)" if flat else "")]
    warnings: list[str] = []
    for e in ENCODINGS:                                     # HDR first: the declaration is the encoding
        if e.transform == "tonemap" and transfer in e.transfer:
            if technical.get("dolby_vision"):
                warnings.append("có metadata Dolby Vision: chuyển về SDR theo lớp HLG/PQ nền, không theo lớp Dolby Vision")
            return Match(e, "high", why + [f"thẻ {transfer} là HDR"], warnings)
    by_device = [e for e in ENCODINGS if e.device and re.search(e.device, device)]
    logs = [e for e in by_device if e.log_look]
    if logs and flat:
        e = logs[0]
        if transfer in ("bt709", "") and e.transform == "lut":
            warnings.append(f"file gắn thẻ {transfer or 'không có thẻ'} nhưng hình phẳng như log: coi là {e.name}")
        return Match(e, "high" if len(logs) == 1 else "medium", why + [f"máy {device.strip()} quay {e.name}, hình phẳng như log"], warnings)
    if logs and not flat:
        return Match(BY_KEY["rec709"], "medium", why + [f"máy quay được {logs[0].name} nhưng hình không phẳng: coi là đã ở Rec.709"], warnings)
    if flat:
        warnings.append("hình phẳng như footage log nhưng không nhận ra máy hay profile: không chuyển màu, cần chọn tay")
        return Match(None, "low", why, warnings)
    if transfer and transfer not in BY_KEY["rec709"].transfer:
        warnings.append(f"transfer {transfer} chưa có trong sổ đăng ký: không chuyển màu")
        return Match(None, "low", why, warnings)
    return Match(BY_KEY["rec709"], "high" if transfer else "medium", why, warnings)
