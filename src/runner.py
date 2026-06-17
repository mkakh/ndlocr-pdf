"""GUI-independent OCR driver (§4.2, §4.3, §4.4, §10).

``run(...)`` is a pure function called by both the GUI (``app.py``) and the
headless CLI (``cli.py``). It orchestrates: parse page spec -> extract pages to
an ASCII workspace as ``doc.pdf`` -> call the upstream engine in-process ->
move/rename the results to the user's output folder -> clean up.
"""

from __future__ import annotations

import contextlib
import io
import re
import shutil
import time
from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import paths
import pagespec
import pdfslice
from pdfslice import PdfOpenError  # re-export for callers

ProgressCallback = Callable[[int, int, str], None]

_INFO_RE = re.compile(r"\[INFO\] OCR PDF page (\d+)/(\d+)")


@dataclass
class OcrResult:
    out_dir: Path
    txt_path: Path | None
    xml_path: Path | None
    json_path: Path | None
    searchable_pdf_path: Path | None
    page_count: int
    overwrote: bool


def run(
    input_pdf,
    pages: str | list[int] | None = None,
    *,
    dpi: float = 150.0,
    enable_tcy: bool = False,
    make_searchable: bool = True,
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
        make_searchable: keep the searchable ``*_text.pdf`` (engine always
            generates it; deleted afterwards when False).
        out_dir: output directory; defaults to ``<input dir>/<stem>_ocr``.
        no_clobber: if the output dir exists, write to a timestamped sibling
            instead of overwriting.
        progress: optional ``(page, total, line)`` callback. When provided, the
            engine's stdout is captured and parsed (not echoed); when ``None``,
            engine progress prints pass straight through to stdout.

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
    try:
        doc_pdf = pdfslice.write_doc(reader, page_list, ws, input_pdf)
        out_pdf = ws / "doc_text.pdf"
        args = _build_namespace(doc_pdf, ws, out_pdf, dpi, enable_tcy)

        _run_engine(ocr, args, progress)

        result = _collect_outputs(
            ws, out_dir, input_pdf.stem, make_searchable, effective_pages, overwrote
        )
    finally:
        _cleanup(ws)

    return result


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------

def _prepare_out_dir(input_pdf: Path, out_dir, no_clobber: bool) -> tuple[Path, bool]:
    if out_dir:
        out_dir = Path(out_dir)
    else:
        out_dir = input_pdf.parent / f"{input_pdf.stem}_ocr"

    exists_nonempty = out_dir.exists() and any(out_dir.iterdir())
    if exists_nonempty and no_clobber:
        # Never overwrite under --no-clobber: claim a fresh directory atomically
        # (exist_ok=False), disambiguating with a counter so two runs in the
        # same second can't land in the same timestamped folder.
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


class _ProgressWriter(io.TextIOBase):
    """stdout sink that parses ``[INFO] OCR PDF page i/n`` lines (§10).

    Captured in the worker thread so ``redirect_stdout`` stays scoped to it.
    """

    def __init__(self, progress: ProgressCallback):
        self._progress = progress
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(s)

    def flush(self) -> None:  # noqa: D401
        if self._buf:
            self._emit(self._buf)
            self._buf = ""

    def _emit(self, line: str) -> None:
        m = _INFO_RE.search(line)
        if m:
            try:
                self._progress(int(m.group(1)), int(m.group(2)), line.strip())
            except Exception:
                pass


def _run_engine(ocr_module, args: Namespace, progress: ProgressCallback | None) -> None:
    if progress is None:
        # CLI passthrough: engine prints go straight to stdout (§5.4).
        ocr_module.process(args)
        return
    writer = _ProgressWriter(progress)
    with contextlib.redirect_stdout(writer):
        ocr_module.process(args)
    writer.flush()


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

    text_pdf = ws / "doc_text.pdf"
    if text_pdf.is_file():
        if make_searchable:
            dst = out_dir / f"{stem}_text.pdf"
            _place(text_pdf, dst)
            result.searchable_pdf_path = dst
        else:
            text_pdf.unlink()

    return result


def _cleanup(ws: Path) -> None:
    """Remove the workspace, tolerant of lingering native file handles (§5.3).

    Only called after ``ocr.process`` has fully returned.
    """
    for _ in range(5):
        shutil.rmtree(ws, ignore_errors=True)
        if not ws.exists():
            return
        time.sleep(0.3)
    # Give up silently; a stale workspace will be cleaned on a later run.
