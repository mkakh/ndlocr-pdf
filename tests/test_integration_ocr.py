"""Engine-backed integration tests (§9 #2, #3b/#3c, #11, #12).

These run the real OCR engine + ONNX models and are therefore slow; they are
skipped automatically when the engine/models are not present (e.g. the fast
lint+unit CI job). They correspond to the [auto] acceptance criteria that need
a real run.
"""

import inspect
import json
import re
from pathlib import Path

import pytest
from pypdf import PdfReader

import paths
import runner

FIX = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIX / "sample.pdf"
FIGURE_SAMPLE = FIX / "sample_with_figure.pdf"
FIGURE_TEXT = "図中認識試験"


def _engine_available() -> bool:
    try:
        return (paths.upstream_src_dir() / "ocr.py").is_file() and (
            paths.model_dir() / "deim-s-1024x1024.onnx"
        ).is_file()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _engine_available(), reason="OCR engine/models not available")

_QUIET = lambda *_: None  # noqa: E731


def _norm(s: str | None) -> str:
    """Whitespace-insensitive text for robust PDF/text-layer comparisons."""
    return "".join((s or "").split())


# --- §9 #3 / #3b: page selection + full-page retention (default) ----------

def test_keep_all_pages_default(tmp_path):
    out = tmp_path / "out"
    result = runner.run(SAMPLE, "2", out_dir=out, ocr_figures=False, progress=_QUIET)

    # all four outputs exist (#2-style)
    assert result.txt_path and result.txt_path.is_file()
    assert result.xml_path and result.xml_path.is_file()
    assert result.json_path and result.json_path.is_file()
    assert result.searchable_pdf_path and result.searchable_pdf_path.is_file()
    assert not result.full_page_failed

    orig = PdfReader(str(SAMPLE))
    full = PdfReader(str(result.searchable_pdf_path))
    total = len(orig.pages)
    # full document preserved in the searchable PDF (#3b)
    assert len(full.pages) == total
    # the searchable PDF's text LAYER, not just page count: the non-selected
    # page is unchanged (no new OCR layer), the selected page gained one.
    assert _norm(full.pages[0].extract_text()) == _norm(orig.pages[0].extract_text())
    assert _norm(full.pages[1].extract_text()) != _norm(orig.pages[1].extract_text())

    # only the selected page's text was OCR'd (#3): page-2's distinctive phrase
    # is present, page-1's distinctive phrase is absent.
    txt = result.txt_path.read_text(encoding="utf-8")
    assert "光学文字認識" in txt          # page 2
    assert "国立国会図書館" not in txt     # page 1


# --- §9 #3c: excerpt-only mode -------------------------------------------

def test_excerpt_only(tmp_path):
    out = tmp_path / "out"
    result = runner.run(SAMPLE, "2", out_dir=out, keep_all_pages=False,
                        ocr_figures=False, progress=_QUIET)
    # excerpt: searchable PDF holds just the selected page
    assert len(PdfReader(str(result.searchable_pdf_path)).pages) == 1


# --- §9 #11: figure OCR on/off -------------------------------------------

def test_figure_ocr_recovers_text(tmp_path):
    on = runner.run(FIGURE_SAMPLE, out_dir=tmp_path / "on", ocr_figures=True, progress=_QUIET)
    off = runner.run(FIGURE_SAMPLE, out_dir=tmp_path / "off", ocr_figures=False, progress=_QUIET)

    on_txt = on.txt_path.read_text(encoding="utf-8")
    off_txt = off.txt_path.read_text(encoding="utf-8")

    # figures ON recovers the in-figure text; OFF misses it (it is the whole
    # point of §4.5). Both still read the body text.
    assert FIGURE_TEXT in on_txt
    assert FIGURE_TEXT not in off_txt
    assert "これは本文の行です" in on_txt
    assert "これは本文の行です" in off_txt

    # The same must hold in the searchable PDF's text LAYER (the figure text is
    # a raster, so it only appears in the PDF when figure OCR added a layer).
    on_pdf = _norm(PdfReader(str(on.searchable_pdf_path)).pages[0].extract_text())
    off_pdf = _norm(PdfReader(str(off.searchable_pdf_path)).pages[0].extract_text())
    assert FIGURE_TEXT in on_pdf
    assert FIGURE_TEXT not in off_pdf


# --- §9 #12(b): upstream lower-level API guard ----------------------------

def test_upstream_api_signatures():
    paths.ensure_upstream_importable()
    import ocr

    for name in ("get_detector", "get_recognizer", "_run_ocr_on_image_array", "embed_text_layer_pdf"):
        assert hasattr(ocr, name), f"upstream ocr.{name} missing"

    rp = inspect.signature(ocr._run_ocr_on_image_array).parameters
    for p in ("detector", "recognizer30", "recognizer50", "recognizer100", "inputname", "img", "outputpath"):
        assert p in rp, f"_run_ocr_on_image_array lost parameter {p}"

    ep = inspect.signature(ocr.embed_text_layer_pdf).parameters
    for p in ("input_pdf", "output_pdf", "page_results"):
        assert p in ep, f"embed_text_layer_pdf lost parameter {p}"


def test_run_ocr_on_image_array_return_keys(tmp_path):
    """#12(b): the page_result dict keys runner depends on are still present."""
    import numpy as np
    import pypdfium2

    paths.ensure_upstream_importable()
    import ocr

    args = runner._build_namespace(SAMPLE, tmp_path, tmp_path / "x.pdf", 150.0, False)
    detector = ocr.get_detector(args)
    rec100 = ocr.get_recognizer(args=args)
    rec30 = ocr.get_recognizer(args=args, weights_path=args.rec_weights30)
    rec50 = ocr.get_recognizer(args=args, weights_path=args.rec_weights50)

    doc = pypdfium2.PdfDocument(str(SAMPLE))
    img = np.array(next(iter(doc.render(pypdfium2.PdfBitmap.to_pil, page_indices=[0], scale=150 / 72))).convert("RGB"))
    doc.close()

    pr = ocr._run_ocr_on_image_array(
        detector=detector, recognizer30=rec30, recognizer50=rec50, recognizer100=rec100,
        inputname="doc_00001.png", img=img, outputpath=str(tmp_path), save_viz=False,
    )
    for key in ("text_layer_lines", "img_width", "img_height", "json_lines", "text", "page_xml", "img_name"):
        assert key in pr, f"page_result lost key {key}"


# --- §9 #12(c): parity vs upstream process() (figures OFF) -----------------

def _normalize_json(s: str) -> dict:
    obj = json.loads(s)
    # drop variable values; keep structure/coords/text/classes
    info = obj.get("pdfinfo", {})
    for k in ("pdf_path", "pdf_name"):
        info.pop(k, None)
    for page in obj.get("pages", []):
        page.pop("img_name", None)
    return obj


def _normalize_xml(s: str) -> str:
    # IMAGENAME carries the per-page image filename; everything else (coords,
    # text, classes, page structure) must match exactly.
    return re.sub(r'IMAGENAME="[^"]*"', 'IMAGENAME="X"', s)


def test_parity_with_upstream_process(tmp_path):
    """runner (figures OFF) reproduces upstream process()'s txt/json output."""
    import pdfslice

    paths.ensure_upstream_importable()
    import ocr

    # One shared single-page doc.pdf so img_name/pdf_path are identical.
    ws_doc = tmp_path / "doc"
    ws_doc.mkdir()
    reader, _ = pdfslice.open_pdf(SAMPLE)
    doc_pdf = pdfslice.write_doc(reader, [1], ws_doc, SAMPLE)

    # upstream run
    up = tmp_path / "up"
    up.mkdir()
    up_args = runner._build_namespace(doc_pdf, up, up / "doc_text.pdf", 150.0, False)
    ocr.process(up_args)

    # runner run (figures OFF)
    rn = tmp_path / "rn"
    rn.mkdir()
    rn_args = runner._build_namespace(doc_pdf, rn, rn / "doc_text.pdf", 150.0, False)
    runner._run_pipeline(ocr, rn_args, rn, ocr_figures=False, make_searchable=True, progress=_QUIET)

    # §9 #12(c): compare normalized .txt, .xml AND .json (XML is re-serialized
    # by runner, so its drift must be guarded too).
    assert (up / "doc.txt").read_text(encoding="utf-8") == (rn / "doc.txt").read_text(encoding="utf-8")
    assert _normalize_xml((up / "doc.xml").read_text(encoding="utf-8")) == \
        _normalize_xml((rn / "doc.xml").read_text(encoding="utf-8"))
    assert _normalize_json((up / "doc.json").read_text(encoding="utf-8")) == \
        _normalize_json((rn / "doc.json").read_text(encoding="utf-8"))
