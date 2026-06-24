"""Full-page-retention composition (§4.2a of SPEC.md).

When only some pages are OCR'd, the engine's searchable PDF (``doc_text.pdf``)
holds just those pages. To keep the original document whole — every page in its
original position, with a text layer added only on the OCR'd pages — we splice
the OCR'd pages back into a copy of the full original PDF.

Pure ``pypdf``; no upstream involvement.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


def compose_full(original_reader: PdfReader, text_pdf, page_list, dest) -> Path:
    """Write a full-page PDF to ``dest``.

    All pages of ``original_reader`` are emitted in order; at each selected page
    position the (text-layered) page from ``text_pdf`` is substituted instead.

    Args:
        original_reader: an open :class:`PdfReader` for the *full* original PDF
            (already decrypted if it was empty-password encrypted).
        text_pdf: path to the engine's searchable PDF holding the OCR'd pages.
        page_list: sorted, 1-based list of OCR'd page numbers. The k-th entry
            corresponds to page k (0-based) of ``text_pdf``.
        dest: output path.

    Returns:
        ``Path(dest)``.

    Raises:
        ValueError: if ``text_pdf`` page count does not match ``page_list``.
    """
    text_reader = PdfReader(str(Path(text_pdf)))
    if len(text_reader.pages) != len(page_list):
        raise ValueError(
            f"ページ数不一致: text_pdf={len(text_reader.pages)} pages, "
            f"selected={len(page_list)}"
        )

    pos = {pageno: i for i, pageno in enumerate(page_list)}

    writer = PdfWriter()
    for idx0, page in enumerate(original_reader.pages):
        pageno = idx0 + 1
        if pageno in pos:
            writer.add_page(text_reader.pages[pos[pageno]])
        else:
            writer.add_page(page)

    dest = Path(dest)
    with open(dest, "wb") as wf:
        writer.write(wf)
    return dest
