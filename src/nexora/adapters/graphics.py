"""Graphics: draws captions as transparent overlays. FFmpeg composites them; it never draws the text itself."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
         "/Library/Fonts/Arial Unicode.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


class CaptionAdapter(Adapter):
    def describe(self) -> Capability:
        return Capability(name="graphics", operations=("caption",), runs="local")

    def environment(self) -> dict:
        return {"font": next((f for f in FONTS if Path(f).is_file()), None)}

    def submit(self, request: Request) -> Result:
        font_path = next((f for f in FONTS if Path(f).is_file()), None)
        if font_path is None:
            raise AdapterError(ErrorCode.UNAVAILABLE, "no font with Vietnamese glyphs was found", retryable=False)
        w, h = int(request.params.get("width", 1280)), int(request.params.get("height", 720))
        font = ImageFont.truetype(font_path, round(h * 0.052))
        image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        lines, current = [], ""
        for word in request.inputs["text"].split():
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= w * 0.82 or not current:
                current = trial
            else:
                lines.append(current); current = word
        lines.append(current)
        line_h = round(h * 0.07)
        top = h - round(h * 0.09) - line_h * len(lines)
        widest = max(draw.textlength(line, font=font) for line in lines)
        pad = round(h * 0.022)
        draw.rounded_rectangle(((w - widest) / 2 - pad * 1.4, top - pad * 0.6, (w + widest) / 2 + pad * 1.4, top + line_h * len(lines) + pad * 0.4),
                               radius=round(h * 0.012), fill=(20, 22, 23, 190))
        for i, line in enumerate(lines):
            draw.text(((w - draw.textlength(line, font=font)) / 2, top + i * line_h), line, font=font, fill=(240, 238, 232, 255))
        out = Path(request.params["out"])
        image.save(out)
        return Result(files=(str(out),))
