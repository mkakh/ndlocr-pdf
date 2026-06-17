"""PDF opening + page extraction into the ASCII workspace (§4.2, §5.3).

The engine names its outputs after the input PDF's stem, so we always feed it a
fixed ASCII filename ``doc.pdf`` placed inside the ASCII workspace. This module
only handles reading the source PDF and producing that ``doc.pdf``.
"""

from __future__ import annotations

from pathlib import Path
import shutil

from pypdf import PdfReader, PdfWriter

DOC_NAME = "doc.pdf"


class PdfOpenError(Exception):
    """Cannot open / decrypt the input PDF (maps to CLI exit code 3).

    Message is Japanese and end-user-facing.
    """


def open_pdf(input_pdf) -> tuple[PdfReader, int]:
    """Open the PDF, applying the empty-password decryption gate (§5.3).

    Returns the reader and its page count. Raises :class:`PdfOpenError` for
    unreadable files, password-protected files that need a non-empty password,
    or empty documents.
    """
    input_pdf = Path(input_pdf)
    if not input_pdf.is_file():
        raise PdfOpenError(f"PDF が見つかりません: {input_pdf}")

    try:
        reader = PdfReader(str(input_pdf))
    except Exception as exc:
        raise PdfOpenError(f"PDF を開けませんでした: {input_pdf}（{exc}）") from exc

    if reader.is_encrypted:
        # Real gate: can we decrypt with an empty password? (empty-password
        # encryption is common; is_encrypted alone is not sufficient.)
        try:
            result = reader.decrypt("")
        except Exception as exc:
            raise PdfOpenError(
                "この PDF はパスワードで保護されているため開けません。"
            ) from exc
        if not result:
            raise PdfOpenError(
                "この PDF はパスワードで保護されているため開けません。"
            )

    try:
        total = len(reader.pages)
    except Exception as exc:
        raise PdfOpenError(f"PDF の構造を読み取れませんでした: {input_pdf}（{exc}）") from exc

    if total < 1:
        raise PdfOpenError("PDF にページがありません。")

    return reader, total


def write_doc(reader: PdfReader, pages: list[int] | None, workspace, original_pdf) -> Path:
    """Write the engine input ``doc.pdf`` into ``workspace``.

    * ``pages is None`` and the source is unencrypted -> straight file copy
      (preserves the original bytes exactly).
    * otherwise -> rebuild via :class:`PdfWriter` with the selected (or all)
      pages, which also strips empty-password encryption so the engine's
      renderer never has to decrypt.

    ``pages`` are 1-based; the list is assumed already validated by ``pagespec``.
    """
    workspace = Path(workspace)
    dest = workspace / DOC_NAME

    if pages is None and not reader.is_encrypted:
        shutil.copyfile(str(Path(original_pdf)), str(dest))
        return dest

    writer = PdfWriter()
    if pages is None:
        for page in reader.pages:
            writer.add_page(page)
    else:
        for n in pages:
            writer.add_page(reader.pages[n - 1])

    with open(dest, "wb") as wf:
        writer.write(wf)
    return dest
