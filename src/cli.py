"""Headless CLI entry (§5.4). Invoked by ``app.py`` when ``--cli`` is present.

Contract:
    <exe> --cli <INPUT.pdf> [--pages 1,3,5-8] [--output DIR] [--dpi 150]
                            [--enable-tcy] [--no-searchable-pdf] [--no-clobber] [--quiet]

Exit codes: 0 success, 2 usage/page-spec error, 3 cannot open PDF, 1 other.
"""

from __future__ import annotations

import argparse
import sys

import runner
from pagespec import PageSpecError
from pdfslice import PdfOpenError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ndlocr-pdf --cli",
        description="NDLOCR-Lite ベースの PDF OCR（ヘッドレス実行）",
    )
    p.add_argument("input", help="入力 PDF ファイル")
    p.add_argument("--pages", default=None, help='対象ページ。例: "1,3,5-8"（省略時は全ページ）')
    p.add_argument("--output", default=None, help="出力フォルダ（省略時は <入力と同じ場所>/<元名>_ocr/）")
    p.add_argument("--dpi", type=float, default=150.0, help="レンダリング DPI（既定 150）")
    p.add_argument("--enable-tcy", action="store_true", help="縦中横を有効化（縦書き資料向け）")
    p.add_argument("--no-searchable-pdf", action="store_true", help="検索可能 PDF を残さない")
    p.add_argument("--no-clobber", action="store_true", help="既存の出力先を上書きせず退避する")
    p.add_argument("--quiet", action="store_true", help="進捗表示を抑制する")
    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)  # exits with code 2 on usage errors

    progress = (lambda *_: None) if args.quiet else None

    try:
        result = runner.run(
            args.input,
            args.pages,
            dpi=args.dpi,
            enable_tcy=args.enable_tcy,
            make_searchable=not args.no_searchable_pdf,
            out_dir=args.output,
            no_clobber=args.no_clobber,
            progress=progress,
        )
    except PageSpecError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2
    except PdfOpenError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - top-level guard, JP message only
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"完了: {result.out_dir}（{result.page_count} ページ）")
        if result.txt_path:
            print(f"  テキスト: {result.txt_path}")
        if result.searchable_pdf_path:
            print(f"  検索可能 PDF: {result.searchable_pdf_path}")
    return 0
