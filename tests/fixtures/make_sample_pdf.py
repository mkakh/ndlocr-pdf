"""Generate tests/fixtures/sample.pdf: an 8+ page PDF with non-empty Japanese
text on every page, large enough that the OCR engine reliably reads it.

Run with the project venv:  uv run python tests/fixtures/make_sample_pdf.py
The produced sample.pdf is committed (it is the #2/#3/smoke fixture).
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent / "sample.pdf"

# Distinct, easily-recognizable Japanese lines per page so that the per-page
# *.txt verification in §9 #3 (pages 1,3,5-8) is meaningful.
PAGES = [
    ["これは一ページ目の文章です。", "国立国会図書館の資料を読み取ります。", "横書きの日本語テキストです。"],
    ["二ページ目の内容になります。", "光学文字認識のテストを行います。", "サンプル文書の確認用ページです。"],
    ["三ページ目のテキストです。", "ページ指定が正しく動くか調べます。", "数字の一二三四五を含みます。"],
    ["四ページ目の文章を記載します。", "検索可能なPDFを生成します。", "日本語の認識精度を確認します。"],
    ["五ページ目に入りました。", "複数ページの処理を検証します。", "東京と京都と大阪の地名です。"],
    ["六ページ目のサンプルです。", "テキスト抽出の動作確認をします。", "春夏秋冬の四季を書きます。"],
    ["七ページ目の内容です。", "出力ファイル名の確認を行います。", "山川草木の文字を並べます。"],
    ["八ページ目の最終ページです。", "全ページの処理が完了しました。", "以上でサンプル文書を終わります。"],
]


def main() -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    c = canvas.Canvas(str(OUT), pagesize=A4)
    width, height = A4
    for i, lines in enumerate(PAGES, start=1):
        c.setFont("HeiseiKakuGo-W5", 28)
        c.drawString(60, height - 90, f"第{i}ページ")
        c.setFont("HeiseiKakuGo-W5", 22)
        y = height - 160
        for line in lines:
            c.drawString(60, y, line)
            y -= 60
        c.showPage()
    c.save()
    print(f"wrote {OUT} ({len(PAGES)} pages)")


if __name__ == "__main__":
    main()
