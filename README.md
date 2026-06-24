# NDLOCR-PDF

非技術者向けの Windows 用 PDF OCR デスクトップアプリです。インストール作業なしで、
「PDF を選ぶ」ボタンから PDF を選んで OCR し、テキストと検索可能 PDF を
出力します。OCR エンジンには国立国会図書館の
[NDLOCR-Lite](https://github.com/ndl-lab/ndlocr-lite) を利用しています。

> 入力はファイル選択ボタンで行います（OS のドラッグ&ドロップは未対応）。

> **日本語（全角）を含むパスに置いても動作します。** `C:\Users\田中\デスクトップ\…`
> のようなフォルダに解凍して実行しても OCR が完了するよう設計されています
> （非 ASCII パス耐性については後述）。

## 使い方（エンドユーザー）

1. Releases から zip をダウンロードして解凍する
2. 中の `ndlocr-pdf.exe` をダブルクリックする
3. 「PDF を選ぶ」で PDF を選択し、対象ページ（空欄＝全ページ）を指定する
4. 「OCR 実行」を押す。完了後「出力フォルダを開く」で結果を確認できる

出力は既定で入力 PDF と同じフォルダ内の `<元のファイル名>_ocr/` に、
`<元のファイル名>.txt` / `.xml` / `.json` と検索可能 PDF `<元のファイル名>_text.pdf`
として保存されます。

- **ページを指定しても文書全体が残ります**（既定）。指定したページだけ文字を読み取り、
  PDF は全ページそのまま・読み取ったページにだけテキスト層が付きます。チェックを外すと
  選択ページだけの抜粋 PDF になります。
- **図・写真の中の文字も読み取ります**（既定）。図領域を切り出して個別に OCR します。
  図が多い文書では処理時間が少し延びるため、チェックで無効化できます。

## コマンドライン（自動化・CI 向け）

同じ exe をヘッドレスで実行できます。

```
ndlocr-pdf.exe --cli <INPUT.pdf> [--pages 1,3,5-8] [--output DIR] [--dpi 150]
                                 [--enable-tcy] [--no-searchable-pdf] [--excerpt-only]
                                 [--no-ocr-figures] [--no-clobber] [--quiet]
```

- `--excerpt-only`: ページ指定時に全ページ保持をやめ、選択ページだけの抜粋 PDF を出す
  （既定は全ページ保持）。
- `--no-ocr-figures`: 図の中の文字の OCR を無効化する（既定は有効）。

終了コード: `0`=成功 / `2`=引数・ページ指定エラー / `3`=PDF を開けない / `1`=その他。

## 開発

開発・ビルド・検証はすべて **Windows + PowerShell** で行います。

- Python: **3.12**（`uv python pin` で固定）
- 依存マネージャ: **uv**
- 上流エンジン: git submodule `external/ndlocr-lite`、**`UPSTREAM_REF = 1.2.3`** に固定
  （`--sourcepdf` を含む最新リリース。改変しない）

```powershell
# 初回のみ
irm https://astral.sh/uv/install.ps1 | iex
git submodule update --init --recursive   # 既存クローンの場合
uv sync                                    # 依存を同期

# 高速な単体テスト（モデル不要）
uv run pytest tests/test_pagespec.py tests/test_figocr.py tests/test_pdfmerge.py -q

# エンジン込みの結合テスト（submodule のモデルが必要・低速）
uv run pytest tests/test_integration_ocr.py -q

# サンプル PDF で CLI 動作確認
uv run python src/app.py --cli tests/fixtures/sample.pdf --pages 1 --output out

# 図 OCR の確認（図中テキストが出力に現れる）
uv run python src/app.py --cli tests/fixtures/sample_with_figure.pdf --output out

# テスト用フィクスチャの再生成（任意）
uv run python tests/fixtures/make_sample_pdf.py
uv run python tests/fixtures/make_sample_with_figure_pdf.py
```

### パッケージング（手動ビルド）

```powershell
uv run python tools/gen_notice.py
uv run flet pack src/app.py -D -n ndlocr-pdf -y `
  --add-data "external/ndlocr-lite/src;ndlocr_src" `
  "--pyinstaller-build-args=--collect-all=onnxruntime" `
  "--pyinstaller-build-args=--collect-all=pypdfium2" `
  "--pyinstaller-build-args=--collect-all=reportlab" `
  "--pyinstaller-build-args=--collect-all=cv2"
```

成果物は `dist/ndlocr-pdf/` に出力されます。`flet build`（Flutter SDK + Visual
Studio が必要）は本用途には過剰なため使いません。

## リリース

`vMAJOR.MINOR.PATCH` の git タグを push すると、GitHub Actions（`windows-latest`）
がビルド → スモークテスト → zip を Releases に添付します（`.github/workflows/build.yml`）。

## 非 ASCII パス耐性

上流エンジンは非 ASCII パスで起動に失敗することがあるため、本アプリでは:

- エンジンに渡す入力 PDF・モデル・出力は常に ASCII の作業フォルダ
  （`%PUBLIC%\ndlocr-pdf\…`）経由にする
- exe 自体が非 ASCII フォルダに置かれた場合は、固定 ASCII ベースへ payload を複製して
  再起動する

ことで、日本語フォルダでも動作します。

## ライセンス

- **本プロジェクトの自作ファイル**（`src/` / `tests/` / `tools/` のほか README・SPEC・
  GitHub Actions・`pyproject.toml` 等）: **MIT License**（`LICENSE`）。
  `external/ndlocr-lite/` と第三者由来ファイルは対象外。
- **OCR エンジン・ONNX モデル**: NDLOCR-Lite に由来し **CC BY 4.0**（国立国会図書館）。
- **依存ライブラリ**: それぞれの寛容ライセンス（Apache / MIT / BSD ほか）。

配布物には帰属表示・変更点・依存ライセンス全文をまとめた `NOTICE` を同梱します
（`tools/gen_notice.py` が `uv` 解決結果から機械生成）。MIT は share-alike では
ないため自前部分は自由に再利用できますが、上流由来部分の CC BY 帰属表示は維持されます。
