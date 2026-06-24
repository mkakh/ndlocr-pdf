"""Unit tests for pdfmerge.compose_full (§4.2a) — no OCR involved.

Builds tiny multi-page PDFs and checks that composition keeps the full page
count, substitutes the OCR'd pages at the right positions, and rejects a page
count mismatch.
"""

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

import pdfmerge


def _make_pdf(path: Path, labels: list[str]) -> None:
    c = canvas.Canvas(str(path))
    for label in labels:
        c.drawString(72, 720, label)
        c.showPage()
    c.save()


def test_compose_preserves_all_pages_and_substitutes(tmp_path):
    original = tmp_path / "orig.pdf"
    text_pdf = tmp_path / "text.pdf"
    dest = tmp_path / "full.pdf"

    # 4-page original; OCR'd pages are 2 and 4 (text PDF has 2 pages).
    _make_pdf(original, ["ORIG-1", "ORIG-2", "ORIG-3", "ORIG-4"])
    _make_pdf(text_pdf, ["OCR-P2", "OCR-P4"])

    pdfmerge.compose_full(PdfReader(str(original)), text_pdf, [2, 4], dest)

    out = PdfReader(str(dest))
    assert len(out.pages) == 4

    texts = [p.extract_text() or "" for p in out.pages]
    # selected positions carry the OCR'd pages; the rest keep the original.
    assert "OCR-P2" in texts[1]
    assert "OCR-P4" in texts[3]
    assert "ORIG-1" in texts[0]
    assert "ORIG-3" in texts[2]
    # the original pages 2/4 were replaced, not kept
    assert "ORIG-2" not in texts[1]
    assert "ORIG-4" not in texts[3]


def test_compose_rejects_page_count_mismatch(tmp_path):
    original = tmp_path / "orig.pdf"
    text_pdf = tmp_path / "text.pdf"
    _make_pdf(original, ["A", "B", "C"])
    _make_pdf(text_pdf, ["X"])  # 1 page

    with pytest.raises(ValueError):
        pdfmerge.compose_full(PdfReader(str(original)), text_pdf, [1, 3], tmp_path / "o.pdf")
