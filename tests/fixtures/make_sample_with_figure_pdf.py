"""Generate tests/fixtures/sample_with_figure.pdf (§4.5 / §9 #11 fixture).

The page carries two kinds of text:

  * normal body text drawn as real PDF text — the base pipeline reads it;
  * a large **photographic figure** (deterministic RGB noise) with SMALL dark
    Japanese text inside it. The layout detector classifies that block as
    ``block_fig`` and does NOT emit the small inner text as a page-level line,
    so the base pipeline misses it. Only figure OCR (§4.5) — which crops the
    figure and re-runs detection+recognition on it — recovers the text.

This regime (block_fig covering text that is too small to be detected as a line
at page scale, but recoverable once the figure is cropped) was found by probing
the real detector; see git history of the fixture spike. The known phrase
``FIGURE_TEXT`` is distinct from the body text so the test can assert it appears
only when figure OCR is enabled.

Run with the project venv:  uv run python tests/fixtures/make_sample_with_figure_pdf.py
The produced sample_with_figure.pdf is committed.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent / "sample_with_figure.pdf"

# Text *inside the figure* — what figure OCR must recover.
FIGURE_TEXT = "図中認識試験"
# Plain body text the base pipeline reads regardless of figure OCR.
BODY_LINES = ["これは本文の行です。", "図の中の文字を読み取る試験用ページです。"]

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\BIZ-UDGothicR.ttc",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    raise RuntimeError("日本語フォントが見つかりませんでした。")


def _figure_image() -> Image.Image:
    """Lighter RGB noise (a 'photo') with small dark text centred in it.

    Deterministic (fixed seed) so the fixture — and the OCR over it — is stable.
    """
    w, h = 1100, 740
    rng = np.random.default_rng(20240624)
    img = Image.fromarray(rng.integers(150, 230, size=(h, w, 3), dtype=np.uint8))
    draw = ImageDraw.Draw(img)
    font = _load_font(22)
    bbox = draw.textbbox((0, 0), FIGURE_TEXT, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2 - bbox[0], (h - th) / 2 - bbox[1]), FIGURE_TEXT, fill=(10, 10, 10), font=font)
    return img


def main() -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    c = canvas.Canvas(str(OUT), pagesize=A4)
    width, height = A4

    c.setFont("HeiseiKakuGo-W5", 24)
    c.drawString(60, height - 90, "図入りサンプル文書")
    c.setFont("HeiseiKakuGo-W5", 18)
    y = height - 150
    for line in BODY_LINES:
        c.drawString(60, y, line)
        y -= 40

    fig = ImageReader(_figure_image())
    img_w = width - 120
    img_h = img_w * 740 / 1100
    c.drawImage(fig, 60, height - 240 - img_h, width=img_w, height=img_h)

    c.showPage()
    c.save()
    print(f"wrote {OUT} (figure text={FIGURE_TEXT!r})")


if __name__ == "__main__":
    main()
