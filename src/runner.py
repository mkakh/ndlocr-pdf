"""GUI-independent OCR driver (§4.2, §4.3, §4.4, §4.5, §10).

``run(...)`` is a pure function called by both the GUI (``app.py``) and the
headless CLI (``cli.py``). It orchestrates: parse page spec -> extract pages to
an ASCII workspace as ``doc.pdf`` -> drive the OCR loop in-process -> (optionally)
splice the OCR'd pages back into the full document -> move/rename the results to
the user's output folder -> clean up.

Single path (§4.2 手順3): the upstream top-level ``ocr.process(args)`` is NOT
used. It returns no ``page_results``, so figure OCR (§4.5) could not integrate
with it, and splitting the path by ``ocr_figures`` would let normal vs figure
runs drift in output/error/progress handling. Instead we reuse the upstream
module-level lower-level functions (``get_detector`` / ``get_recognizer`` /
``_run_ocr_on_image_array`` / ``embed_text_layer_pdf``) and replicate
``process_pdf_documents``'s serialization here. The drift this couples us to is
guarded by the §9 #12 tests against the pinned ``UPSTREAM_REF`` submodule.
"""

from __future__ import annotations

import json
import shutil
import time
from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import figocr
import paths
import pagespec
import pdfmerge
import pdfslice
from pdfslice import PdfOpenError  # re-export for callers

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class OcrResult:
    out_dir: Path
    txt_path: Path | None
    xml_path: Path | None
    json_path: Path | None
    searchable_pdf_path: Path | None
    page_count: int
    overwrote: bool
    full_page_failed: bool = False


def run(
    input_pdf,
    pages: str | list[int] | None = None,
    *,
    dpi: float = 150.0,
    enable_tcy: bool = False,
    make_searchable: bool = True,
    keep_all_pages: bool = True,
    ocr_figures: bool = True,
    out_dir=None,
    no_clobber: bool = False,
    progress: ProgressCallback | None = None,
) -> OcrResult:
    """Run OCR on ``input_pdf``.

    Args:
        input_pdf: path to the source PDF.
        pages: page expression string (``"1,3,5-8"``), ``None``/empty for all
            pages, or an already-parsed 1-based ``list[int]``.
        dpi: render DPI passed to the engine (``pdf_render_dpi``).
        enable_tcy: enable 縦中横 recognition.
        make_searchable: keep the searchable ``*_text.pdf`` (generated, then
            deleted afterwards when False).
        keep_all_pages: when pages are selected, output the searchable PDF with
            the *whole* document preserved and the text layer only on the OCR'd
            pages (§4.2a). ``False`` -> excerpt of selected pages only. Ignored
            when all pages are processed (the result is identical).
        ocr_figures: also OCR text inside figure regions (§4.5). ``False`` ->
            figures are skipped (upstream's default behaviour).
        out_dir: output directory; defaults to ``<input dir>/<stem>_ocr``.
        no_clobber: if the output dir exists, write to a timestamped sibling
            instead of overwriting.
        progress: optional ``(page, total, line)`` callback. When ``None`` the
            progress lines are printed to stdout (CLI passthrough, §5.4).

    Returns:
        :class:`OcrResult`.
    """
    input_pdf = Path(input_pdf)

    paths.ensure_upstream_importable()
    import ocr  # noqa: E402  (import after sys.path is set)

    reader, total = pdfslice.open_pdf(input_pdf)

    if isinstance(pages, list):
        page_list: list[int] | None = pages
    else:
        page_list = pagespec.parse_pages(pages, total)

    effective_pages = total if page_list is None else len(page_list)

    out_dir, overwrote = _prepare_out_dir(input_pdf, out_dir, no_clobber)

    ws = paths.ascii_workspace()
    full_page_failed = False
    try:
        doc_pdf = pdfslice.write_doc(reader, page_list, ws, input_pdf)
        out_pdf = ws / "doc_text.pdf"
        args = _build_namespace(doc_pdf, ws, out_pdf, dpi, enable_tcy)

        _run_pipeline(ocr, args, ws, ocr_figures, make_searchable, progress)

        # Decide which PDF becomes the user's searchable output.
        searchable_name = "doc_text.pdf"
        if make_searchable and keep_all_pages and page_list is not None:
            try:
                full_pdf = ws / "doc_full.pdf"
                pdfmerge.compose_full(reader, out_pdf, page_list, full_pdf)
                searchable_name = "doc_full.pdf"
            except Exception:
                # §4.2a: fall back to the excerpt, but surface that we did.
                full_page_failed = True

        result = _collect_outputs(
            ws, out_dir, input_pdf.stem, make_searchable,
            effective_pages, overwrote, searchable_name,
        )
        result.full_page_failed = full_page_failed
    finally:
        _cleanup(ws)

    return result


# --------------------------------------------------------------------------
# in-process OCR loop (replaces upstream process_pdf_documents; §4.2 手順3)
# --------------------------------------------------------------------------

def _emit(progress: ProgressCallback | None, i: int, total: int, line: str) -> None:
    if progress is not None:
        try:
            progress(i, total, line)
        except Exception:
            pass
    else:
        print(line)


def _run_pipeline(
    ocr,
    args: Namespace,
    ws: Path,
    ocr_figures: bool,
    make_searchable: bool,
    progress: ProgressCallback | None,
) -> int:
    """Render + OCR every page of ``args.sourcepdf``, serialize, embed text layer.

    Output files (``doc.txt/.xml/.json`` and, when ``make_searchable``,
    ``doc_text.pdf``) are written under ``ws`` in exactly the format upstream's
    ``process_pdf_documents`` produces (§9 #12 parity).
    """
    import numpy as np
    import pypdfium2

    doc_pdf = Path(args.sourcepdf)
    output_stem = doc_pdf.stem  # "doc"
    dpi = float(getattr(args, "pdf_render_dpi", 150.0))
    render_scale = max(dpi, 1.0) / 72.0

    detector = ocr.get_detector(args)
    recognizer100 = ocr.get_recognizer(args=args)
    recognizer30 = ocr.get_recognizer(args=args, weights_path=args.rec_weights30)
    recognizer50 = ocr.get_recognizer(args=args, weights_path=args.rec_weights50)

    page_results: list[dict] = []
    all_json_contents: list = []
    page_infos: list[dict] = []
    all_text_pages: list[str] = []
    all_page_xml: list[str] = []

    pdf_doc = pypdfium2.PdfDocument(str(doc_pdf))
    try:
        n = len(pdf_doc)
        for page_index in range(n):
            page_name = f"{output_stem}_{page_index + 1:05}.png"
            _emit(progress, page_index + 1, n, f"[INFO] OCR PDF page {page_index + 1}/{n}")

            rendered = pdf_doc.render(
                pypdfium2.PdfBitmap.to_pil,
                page_indices=[page_index],
                scale=render_scale,
            )
            pil_image = next(iter(rendered)).convert("RGB")
            img = np.array(pil_image)

            page_result = ocr._run_ocr_on_image_array(
                detector=detector,
                recognizer30=recognizer30,
                recognizer50=recognizer50,
                recognizer100=recognizer100,
                inputname=page_name,
                img=img,
                outputpath=str(ws),
                save_viz=False,
            )

            if ocr_figures:
                added = figocr.augment_page(
                    ocr, detector, recognizer30, recognizer50, recognizer100,
                    img, page_result, str(ws),
                )
                if added:
                    _emit(progress, page_index + 1, n,
                          f"図を処理中… {page_index + 1}/{n} ページ（{added} 箇所）")

            page_results.append(page_result)
            all_json_contents.append(page_result["json_lines"])
            page_infos.append({
                "page_index": page_index,
                "img_width": page_result["img_width"],
                "img_height": page_result["img_height"],
                "img_name": page_result["img_name"],
            })
            all_text_pages.append(page_result["text"])
            all_page_xml.append(page_result["page_xml"])
    finally:
        pdf_doc.close()

    # --- serialize identically to upstream process_pdf_documents ---
    (ws / f"{output_stem}.xml").write_text(
        "<OCRDATASET>\n" + "\n".join(all_page_xml) + "\n</OCRDATASET>",
        encoding="utf-8",
    )
    (ws / f"{output_stem}.txt").write_text(
        "\n\n".join(all_text_pages),
        encoding="utf-8",
    )
    alljsonobj = {
        "contents": all_json_contents,
        "pdfinfo": {
            "pdf_path": str(doc_pdf),
            "pdf_name": doc_pdf.name,
            "page_count": len(page_results),
            "render_dpi": dpi,
        },
        "pages": page_infos,
    }
    (ws / f"{output_stem}.json").write_text(
        json.dumps(alljsonobj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if make_searchable:
        ocr.embed_text_layer_pdf(
            input_pdf=str(doc_pdf),
            output_pdf=str(args.pdf_output),
            page_results=page_results,
            visible_text=bool(getattr(args, "pdf_visible_text", False)),
        )

    return len(page_results)


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------

def _prepare_out_dir(input_pdf: Path, out_dir, no_clobber: bool) -> tuple[Path, bool]:
    if out_dir:
        out_dir = Path(out_dir)
    else:
        out_dir = input_pdf.parent / f"{input_pdf.stem}_ocr"

    if no_clobber:
        # Never overwrite. Try to claim the base dir itself atomically; this
        # both honors SPEC "出力先が既存なら上書きせず" (an existing dir — even
        # empty — is not reused) and closes the concurrent-start race (only one
        # process can create it). On any clash fall back to a timestamped/
        # counter sibling, also claimed atomically.
        try:
            out_dir.mkdir(parents=True, exist_ok=False)
            return out_dir, False
        except FileExistsError:
            pass
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = out_dir.parent / f"{out_dir.name}_{ts}"
        candidate = base
        n = 1
        while True:
            try:
                candidate.mkdir(parents=True, exist_ok=False)
                return candidate, False
            except FileExistsError:
                candidate = base.parent / f"{base.name}_{n}"
                n += 1

    exists_nonempty = out_dir.exists() and any(out_dir.iterdir())
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir, exists_nonempty


def _build_namespace(doc_pdf: Path, out_dir: Path, out_pdf: Path, dpi: float, enable_tcy: bool) -> Namespace:
    md = paths.model_dir()
    cd = paths.config_dir()
    return Namespace(
        # input/output
        sourcedir=None,
        sourceimg=None,
        sourcepdf=str(doc_pdf),
        output=str(out_dir),
        viz=False,
        pdf_output=str(out_pdf),
        pdf_render_dpi=float(dpi),
        pdf_visible_text=False,
        # detector
        det_weights=str(md / "deim-s-1024x1024.onnx"),
        det_classes=str(cd / "ndl.yaml"),
        det_score_threshold=0.2,
        det_conf_threshold=0.25,
        det_iou_threshold=0.2,
        simple_mode=False,
        # recognizer cascade
        rec_weights30=str(md / "parseq-ndl-24x256-30-tiny-189epoch-tegaki3-r8data-202604.onnx"),
        rec_weights50=str(md / "parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx"),
        rec_weights=str(md / "parseq-ndl-24x768-100-tiny-153epoch-tegaki3-r8data-202604.onnx"),
        rec_classes=str(cd / "NDLmoji.yaml"),
        device="cpu",
        enable_tcy=bool(enable_tcy),
        json_only=False,
    )


def _place(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))


def _collect_outputs(
    ws: Path,
    out_dir: Path,
    stem: str,
    make_searchable: bool,
    page_count: int,
    overwrote: bool,
    searchable_name: str,
) -> OcrResult:
    result = OcrResult(
        out_dir=out_dir,
        txt_path=None,
        xml_path=None,
        json_path=None,
        searchable_pdf_path=None,
        page_count=page_count,
        overwrote=overwrote,
    )

    for ext, attr in ((".txt", "txt_path"), (".xml", "xml_path"), (".json", "json_path")):
        src = ws / f"doc{ext}"
        if src.is_file():
            dst = out_dir / f"{stem}{ext}"
            _place(src, dst)
            setattr(result, attr, dst)

    text_pdf = ws / searchable_name
    if make_searchable and text_pdf.is_file():
        dst = out_dir / f"{stem}_text.pdf"
        _place(text_pdf, dst)
        result.searchable_pdf_path = dst

    return result


def _cleanup(ws: Path) -> None:
    """Remove the workspace, tolerant of lingering native file handles (§5.3).

    Only called after every step that touches files under ``ws`` (OCR loop,
    figure OCR, text-layer PDF, full-page composition) has fully returned.
    """
    for _ in range(5):
        shutil.rmtree(ws, ignore_errors=True)
        if not ws.exists():
            return
        time.sleep(0.3)
    # Give up silently; a stale workspace will be cleaned on a later run.
