"""Graphics: draws captions as transparent overlays. FFmpeg composites them; it never draws the text itself."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
         "/Library/Fonts/Arial Unicode.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


SERIF = ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf", "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"]


class CaptionAdapter(Adapter):
    def describe(self) -> Capability:
        return Capability(name="graphics", operations=("caption", "poster"), runs="local")

    def environment(self) -> dict:
        return {"font": next((f for f in FONTS if Path(f).is_file()), None)}

    def _poster(self, request: Request, font_path: str) -> Result:
        """A thumbnail with its title on it: a frame of the video, darkened towards the bottom, with a few large words."""
        base = Image.open(request.inputs["image"]).convert("RGB")
        w, h = base.size
        shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        veil = ImageDraw.Draw(shade)
        for y in range(h // 2, h):                                     # darker towards the bottom, where the words sit
            veil.line([(0, y), (w, y)], fill=(8, 10, 14, round(210 * (y - h / 2) / (h / 2))))
        image = Image.alpha_composite(base.convert("RGBA"), shade)
        draw = ImageDraw.Draw(image)
        words = request.inputs["text"].split()
        size = round(h * 0.13)
        while size > h * 0.05:
            font = ImageFont.truetype(font_path, size)
            lines, current = [], ""
            for word in words:
                trial = f"{current} {word}".strip()
                if draw.textlength(trial, font=font) <= w * 0.88 or not current:
                    current = trial
                else:
                    lines.append(current); current = word
            lines.append(current)
            if len(lines) <= 3:
                break
            size = round(size * 0.88)
        line_h = round(size * 1.16)
        top = h - round(h * 0.07) - line_h * len(lines)
        for i, line in enumerate(lines):
            draw.text((round(w * 0.06), top + i * line_h), line, font=font, fill=(255, 255, 255, 255), stroke_width=max(2, size // 18), stroke_fill=(0, 0, 0, 255))
        out = Path(request.params["out"])
        image.convert("RGB").save(out, quality=90)
        return Result(files=(str(out),))

    def submit(self, request: Request) -> Result:
        faces = (SERIF + FONTS) if request.params.get("typeface") == "serif" else FONTS
        font_path = next((f for f in faces if Path(f).is_file()), None)
        if font_path is None:
            raise AdapterError(ErrorCode.UNAVAILABLE, "no font with Vietnamese glyphs was found", retryable=False)
        if request.operation == "poster":
            return self._poster(request, font_path)
        w, h = int(request.params.get("width", 1280)), int(request.params.get("height", 720))
        scale = float(request.params.get("scale", 1.0))                # the brand profile's caption size
        font = ImageFont.truetype(font_path, round(h * 0.052 * scale))
        image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        def wrap(limit: float) -> list[str]:
            out, current = [], ""
            for word in request.inputs["text"].split():
                trial = f"{current} {word}".strip()
                if draw.textlength(trial, font=font) <= limit or not current:
                    current = trial
                else:
                    out.append(current); current = word
            return out + [current]

        lines = wrap(w * 0.82)
        if len(lines) > 1:
            # Even out the lines, so that a caption never ends on one stranded word.
            even = wrap(min(w * 0.82, draw.textlength(request.inputs["text"], font=font) / len(lines) * 1.12))
            lines = even if len(even) == len(lines) else lines
        line_h = round(h * 0.07 * scale)
        place = request.params.get("position", "bottom")
        top = (round(h * 0.08) if place == "top" else (h - line_h * len(lines)) // 2 if place == "middle" else h - round(h * 0.09) - line_h * len(lines))
        widest = max(draw.textlength(line, font=font) for line in lines)
        pad = round(h * 0.022)
        draw.rounded_rectangle(((w - widest) / 2 - pad * 1.4, top - pad * 0.6, (w + widest) / 2 + pad * 1.4, top + line_h * len(lines) + pad * 0.4),
                               radius=round(h * 0.012), fill=(20, 22, 23, 190))
        for i, line in enumerate(lines):
            draw.text(((w - draw.textlength(line, font=font)) / 2, top + i * line_h), line, font=font, fill=tuple(request.params.get("colour") or (240, 238, 232)) + (255,))
        logo = request.params.get("logo")
        if logo and Path(logo).is_file():                      # the brand's mark, small, in the corner the caption does not use
            mark = Image.open(logo).convert("RGBA")
            size = round(h * 0.09)
            mark.thumbnail((size * 3, size))
            margin = round(h * 0.04)
            image.alpha_composite(mark, (w - mark.width - margin, h - mark.height - margin if place == "top" else margin))
        out = Path(request.params["out"])
        image.save(out)
        return Result(files=(str(out),))
