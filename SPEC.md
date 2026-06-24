# 仕様書: NDLOCR-Lite ベース Windows PDF OCR デスクトップアプリ

> この文書は Claude Code への実装指示として使うことを想定したドラフトです。
> 「決定事項」は変更しないこと。「未決事項」は実装前に確認すること。

---

## 0. 開発環境セットアップ（空ディレクトリから最初に実行）

開発・ビルド・検証はすべて **Windows 上で行う（確定）**。`flet pack` と exe 検証が Windows 必須で、開発機を分けると往復が無駄なため統一する。本節はカレントの空ディレクトリで Claude Code が最初に実行する手順。シェルは **PowerShell**。

**確定値**
- Python: **3.12**（固定）。NDLOCR-Lite 上流のリリースビルドも 3.12（`build-flet-cross.yml`）。
- `UPSTREAM_REF` = **`1.2.3`**（NDLOCR-Lite の最新リリース。`--sourcepdf` を含む。**注意: タグ `1.2.1` には PDF 対応が無い**。1.2.2 から入った）。出自は GitHub の Releases ページで確認すること（README の表記やタグ一覧は古い/不完全なことがある）: https://github.com/ndl-lab/ndlocr-lite/releases
- 依存マネージャ: **uv**。
- プロジェクト名: `pyproject.toml` の `project.name = "ndlocr-pdf"`、`version` は **タグ駆動**（§7 参照、初期 `0.1.0`）。

**手順（PowerShell）**
```powershell
# 1. uv を導入（未インストール想定）
irm https://astral.sh/uv/install.ps1 | iex
#    新しいシェルを開くか、$env:Path を再読込して uv を有効化

# 2. git リポジトリ化（submodule に必要）
git init

# 3. uv プロジェクト初期化（--bare で hello.py 等のサンプルを作らない）& Python 固定
uv init --bare .
uv python pin 3.12          # .python-version 生成（uv が 3.12 を取得）

# 4. 上流を submodule として固定取り込み（改変しない）
git submodule add https://github.com/ndl-lab/ndlocr-lite external/ndlocr-lite
git -C external/ndlocr-lite checkout 1.2.3
git add .gitmodules external/ndlocr-lite

# 5. 取り込み検証（PDF 対応が入っているか fail-fast）
if (-not (Select-String -Path external/ndlocr-lite/src/ocr.py -Pattern '--sourcepdf' -Quiet)) {
    Write-Error 'ERROR: submodule does not contain PDF support'; exit 1
}

# 6. 依存追加（上流 requirements.txt のピンをそのまま継承＝二重管理を避ける）
#    flet==0.27.6 等は requirements.txt に含まれるので個別指定しない。
uv add -r external/ndlocr-lite/requirements.txt
uv add --dev pyinstaller    # flet pack の下回り
```

**コミット対象**: `pyproject.toml`, `uv.lock`, `.python-version`, `.gitmodules`, `external/ndlocr-lite`（gitlink）, `src/`（`_version.py` の dev 既定含む）, `tests/fixtures/sample.pdf`, `tests/fixtures/sample_with_figure.pdf`。venv（`.venv`）と `build/` `dist/` はコミットしない（`.gitignore` を用意）。

> スモークテスト＆受け入れ #2/#3 用に `tests/fixtures/sample.pdf`（**実際に OCR 可能な日本語テキストを含む複数ページ PDF、8 ページ以上**）をリポジトリに用意・コミットする。ページ選択テスト `1,3,5-8`（§9 #3）が成立するよう 8 ページ以上とし、各ページに非空のテキストを置く（`*.txt` 検証が「テキストが出ている」ことを意味するように）。1 ページのスモークが要るときは `--pages 1` で部分実行する。

> 図OCR（§4.5・受け入れ #11）用に `tests/fixtures/sample_with_figure.pdf` を用意・コミットする。**図領域（`block_fig` 等として検出される画像/枠）の中に、既知の日本語テキストを焼き込んだページ**を含めること（本文行ではなく図の内部に文字がある状態）。図OCR ON でその既知テキストが出力に現れ、`--no-ocr-figures` で現れないことを検証できるようにする。

> 上流の ONNX モデルは submodule に含まれるので、init すれば取得される（自リポジトリの履歴は汚さない）。
> 依存は上流 `requirements.txt` を単一の真実として継承するため、submodule 更新時もバージョンが静かにズレない。

---

## 1. 目的とゴール

非技術者（計算機に強くないユーザー）が、Windows 上で **インストール作業なし**に PDF を OCR できるデスクトップアプリを作る。

体験のゴール:

1. releases から zip をダウンロードして解凍する
2. 中の起動ファイルをダブルクリックする
3. PDF をドラッグ&ドロップ（または「開く」で選択）し、対象ページを指定する
4. OCR が走り、結果（テキスト / 検索可能 PDF）が出力される

ユーザーには **Python も git も pip も一切要求しない**。

**想定文書**: 近現代の**横書き主体**。ただし縦書き資料（古典籍・新聞等）にも対応できるよう、縦中横（`--enable-tcy`）は **GUI の任意トグル（既定 OFF）**として提供する。

---

## 2. スコープ

### やること（In scope）
- 既存 OCR エンジン NDLOCR-Lite を内部利用する薄いドライバ + GUI を新規開発する
- **ページ指定機能**（NDLOCR-Lite 本体に無い不足機能の一つ）を追加する
- **部分OCR時の全ページ保持出力**（必須）: ページ指定で OCR したとき、検索可能 PDF を「選択ページだけの抜粋」ではなく**元の全ページを保ったまま、選択ページにだけテキスト層を載せた PDF**として出力する。**既定 ON**、従来の抜粋出力も選択可能（§4.2a）
- **図領域内テキストの OCR（必須）**: 本体の既定パイプラインは図（`block_fig` 等）の中の文字を認識しない。本アプリで図領域を追加処理し、図中テキストにもテキスト層を載せる。**既定 ON**、切替可（§4.5）
- Windows 向け自己完結バイナリのパッケージングと CI ビルド

### やらないこと（Out of scope / 再実装禁止）
- PDF→画像のレンダリング: **本体が pypdfium2 で実装済み。書き直さない**
- OCR パイプライン本体（レイアウト認識・文字認識・読み順整序の**アルゴリズム**）: 書き換えない。図中テキスト対応（§4.5）は本体の検出器/認識器を**そのまま再利用して領域を追加処理する**ものであり、アルゴリズムの改変ではない（上流ファイルは編集しない／§4.1）。
- 検索可能 PDF 生成のコア: 本体の `embed_text_layer_pdf` を使う（全ページ保持の合成は §4.2a でアプリ側が pypdf で行い、テキスト層生成自体は本体に任せる）
- GPU 対応: 当面 CPU 固定（本体に `--device cuda` はあるが対象外）

---

## 3. 前提（上流コードの実測事実）

> 2026-06-09 マージのコードを実測した結果。README のコマンドライン節はこれを反映していない。

- 上流: `https://github.com/ndl-lab/ndlocr-lite`（ライセンス **CC BY 4.0**）
- エントリ: `src/ocr.py`
  - `process(args)`: 入力種別を振り分ける最上位関数
  - `process_pdf_documents(args, pdf_paths: list[str])`: PDF 処理本体
  - `embed_text_layer_pdf(input_pdf, output_pdf, page_results, visible_text=False)`: 透明テキスト層 PDF 生成
- 本体 CLI が既に対応している引数（抜粋）:
  - `--sourcepdf`（PDF 直接入力）、`--output`（必須）
  - `--pdf-output`（検索可能 PDF の出力先）
  - `--pdf-render-dpi` / `--pdf-dpi`（既定 150.0、`render_scale = dpi/72`）
  - `--viz`, `--json-only`, `--enable-tcy`, `--simple-mode`, `--device {cpu,cuda}`
  - det/rec の重み・クラス定義パス（既定値あり、後述）
- **PDF レンダリングは pypdfium2 を使用**（`PdfDocument(...).render(...)`）
- 出力は `output_stem.txt` / `.xml` / `.json`、加えて検索可能 PDF（既定 `output_stem_text.pdf`）
- 既定モデル/設定パスは `base_dir = Path(ocr.py).resolve().parent` 基準:
  - `model/deim-s-1024x1024.onnx`
  - `model/parseq-ndl-24x256-30-...onnx` / `-24x384-50-...onnx` / `-24x768-100-...onnx`
  - `config/ndl.yaml`, `config/NDLmoji.yaml`
- 依存（`requirements.txt`、既に含む）: `pypdfium2==4.30.0`, `pypdf==6.4.0`, `flet==0.27.6`, `onnxruntime`, `opencv-python-headless`, `numpy`, `pillow`, `reportlab`, `lxml`, ほか

### 既知の制約・落とし穴
- `ocr.py` は **相対 import 前提**（`from deim import DEIM`, `from parseq import PARSEQ`, `from reading_order...`, `from ndl_parser...`）。`src/` を `sys.path` 先頭に追加してから import すること。
- 本体には **ページ指定が無い**。`process_pdf_documents` は `for page_index in range(len(pdf_doc))` で全ページ固定。
- **検索可能 PDF は入力 PDF と同じページ集合で作られる**。`embed_text_layer_pdf(input_pdf, output_pdf, page_results)` は `len(reader.pages) == len(page_results)` を**厳格に要求**し、`zip(reader.pages, page_results)` で1対1にテキスト層を載せる。よって抽出済み（選択ページのみ）の PDF を食わせると、出力 PDF も選択ページだけになる。全ページ保持出力（§4.2a）はこの制約を踏まえ、アプリ側でページ差し替え合成して実現する。
- **認識対象は `LINE` 要素のみ**。`process_pdf_documents`→`_run_ocr_on_image_array` は検出後 `root.findall(".//LINE")` に対してのみ認識（`process_cascade`）を走らせる。検出クラス（`config/ndl.yaml`）には `6: block_fig` / `11: block_chart` / `15: block_table` 等の図系ブロックがあるが、これらは**ブロックとして検出されるだけで行（LINE）にはならず、内部の文字は認識されない**。これが「出力 PDF の図にテキスト層が乗らない」の根本原因。図中テキスト対応（§4.5）はこの図系ブロック領域を切り出して**本体の検出器/認識器に再投入**して補う。
- 上流 README の注意: **全角文字を含むパスに配置すると起動しないことがある**。本アプリの対象ユーザー（日本語圏の非技術者）の既定パスは `C:\Users\田中\...` のように非 ASCII を含むため、これは例外ではなく**既定環境**。READMEへの注記では不十分。§6.1 の必須要件として扱う。

---

## 4. アーキテクチャ（決定事項）

### 4.1 上流の取り込み方
- **git submodule** で `external/ndlocr-lite/` に取り込む。上流コードを自リポジトリに複製しない（出自が明示的・モラル的にクリーン・上流の巨大 ONNX モデルで自リポジトリ履歴を汚さない）。
- submodule は**特定タグ/コミットに固定**する（再現性のため）。固定値を `UPSTREAM_REF` として README に記録する。更新は `git submodule update --remote` を意図的に実行したときだけ。
- **submodule 更新時の必須ゲート**: gitlink もしくは `UPSTREAM_REF` を変更する PR では、§9 #12(c) のパリティテスト（上流 `process()` vs runner の出力一致）を CI 必須にする。runner は上流の下位関数と出力形式に依存して一本化している（§4.2 手順3）ため、ここで意味的 drift を検知する。
- 上流コードは **改変しない**（パッチ不要にするのが本設計の主眼。改変が必要なら submodule では不都合になるため、その時点で「未決事項」に戻し fork へ切り替えを検討する）。
- エンドユーザーは exe を使うため submodule に一切触れない。submodule の init が要るのは開発者と CI のみ。

### 4.2 ページ指定の実現方法と出力命名（ブロッカー1/3 統合）
本体を触らず、**入力 PDF を前処理 → ASCII ワークスペースで実行 → ユーザー名で結果を戻す**で実現する。

重要事実: `process_pdf_documents` は `output_stem = pdf_path_obj.stem`（**入力 PDF のファイル名**）で `.txt/.xml/.json` を命名する。よって temp 名の PDF を食わせると出力が `tmpXXXX.txt` 等になる。これを避けるため、エンジンに渡す PDF 名と作業ディレクトリを制御する。

手順:
1. ページ式をパース（`parse_pages`）。`None`（全ページ）なら抽出スキップ、`list[int]` なら `pypdf.PdfWriter` で該当ページを抽出。
   - 順序の明示: `parse_pages(spec, total)` は総ページ数 `total` を必要とするため、**先に `PdfReader` で PDF を開いてページ数を取得してから**パースする。範囲外（例 `999`）の検証は実ページ数に対して行う。
2. **ASCII 作業ディレクトリ**（§6.1 の `ascii_workspace()`）に、**固定 ASCII 名 `doc.pdf`** として入力（または抽出結果）を置く。全ページ&元PDFが ASCII パスでも、命名統一のため常にこの作業ディレクトリにコピーする。
3. `Namespace` の `sourcepdf=<ws>/doc.pdf`、`output=<ws>`、`pdf_output=<ws>/doc_text.pdf` を ASCII パスで組み立てる。**処理経路は常に runner で一本化する（`ocr.process(args)` は通常経路では呼ばない）**。`process()` は `page_results` を返さず図OCR結果を統合できないこと、また経路を ON/OFF で分けると通常OCRと図OCRで**出力・エラー処理・進捗・ページ指定の挙動がズレやすい**ことから、`ocr_figures` の ON/OFF に関わらず同一経路にする。`runner.py` が `process_pdf_documents` 相当の処理を下位関数で実行する: pypdfium2 で各ページをレンダリングし、`ocr._run_ocr_on_image_array(...)` の結果をページ順の `page_results` として保持、（図OCR ON なら）図OCR結果を同じ結果オブジェクトへ統合してから、上流と同じ形式で `doc.txt/.xml/.json` をシリアライズし、`ocr.embed_text_layer_pdf(...)` で `doc_text.pdf` を生成する。エンジンへ渡すパスは引き続き全て ASCII とする。
   - **一本化のコスト（要保守）**: `.txt/.xml/.json` のシリアライズと、再利用する上流下位関数の API 契約に runner が依存する。submodule 更新時のズレ検知は §9 #12 の契約/ガードテストで担保する（submodule は `UPSTREAM_REF` で固定）。
4. **全ページ保持の合成（§4.2a。ページ指定時かつ既定の全ページ保持モードのとき）**: エンジンが出した `doc_text.pdf`（選択ページ分のテキスト層付き）を、**元の全ページ PDF の該当ページへ差し戻して**合成する。抜粋モードならこの手順をスキップして `doc_text.pdf` をそのまま使う。
5. 生成物を**ユーザーの出力先**（既定 `<入力PDFと同フォルダ>/<元stem>_ocr/`）へ移動し、`doc.*` を**元のファイル名 stem へリネーム**する。出力先が非 ASCII でも、ここはファイル移動だけなのでエンジンの C 層を経由せず安全。
   - **衝突時の挙動（Medium5）**: 出力フォルダが既に在る場合は**そのまま再利用し、同名ファイルは上書き**する（同じ入力 → 同じ出力先で予測可能、フォルダ乱立を避ける）。上書きが起きる場合は GUI で軽く知らせる（「既存の結果を上書きします」）。`--cli` は確認なしで上書き（`--no-clobber` 指定時のみタイムスタンプ付き `<元stem>_ocr_YYYYMMDD-HHMMSS/` に退避）。
6. 作業ディレクトリを片付ける（§5.3 の削除規約に従う）。

> `pypdf` は新規依存ゼロ。エンジンへ渡すパスは全て ASCII・stem は固定なので、ブロッカー1（非ASCIIパス）とブロッカー3（stem 汚染）を同時に解消する。検索可能 PDF のページ集合は §4.2a のモードで決まる（既定は全ページ保持）。

### 4.2a 全ページ保持出力（必須・既定 ON）
ページ指定して OCR したとき、検索可能 PDF を「選択ページだけの抜粋」ではなく **元の全ページを保ったまま、選択ページにのみテキスト層が載った PDF** として出力する。非選択ページは元のまま（テキスト層なし）で残す。

理由: 「3,5-8ページだけ OCR したいが、納品/保存するのは元の文書全体」というのが対象ユーザーの自然な期待。抜粋だけ返すとページ番号がずれ、元文書との対応が壊れる。

実現（上流改変なし・`pypdf` のみ）:
- §4.2 手順1で開いた**元の全ページ PDF**（`PdfReader`、ASCII 作業ディレクトリにコピー済みの原本 `orig.pdf` を別途保持）と、エンジンが選択ページから生成した `doc_text.pdf` を両方読む。
- `PdfWriter` に元 PDF の全ページを順に積み、**選択ページの位置には `doc_text.pdf` の対応ページ（テキスト層付き）を差し込む**。選択ページ → `doc_text.pdf` ページの対応は §4.2 手順1の昇順ページリストで一意に決まる（k 番目の選択ページ = `doc_text.pdf` の k ページ目）。
- 結果を最終的な検索可能 PDF（`<元stem>_text.pdf`）として書き出す。`.txt/.xml/.json` は従来どおり**選択ページ分のみ**（OCR したページのテキストだけ）で問題ない（全文ファイルに非OCRページの空文字を混ぜない）。

モード切替:
- **全ページ保持（既定）** / **抜粋のみ（従来挙動）** を GUI のチェックと CLI フラグで選べる（§5.1・§5.4）。
- 全ページ未指定（= 全ページ OCR）のときは両モードで結果が同一なので、合成はスキップしてよい（`doc_text.pdf` がそのまま全ページ）。
- 暗号化・特殊メタデータ等で差し込みに失敗した場合は、抜粋 PDF を保持しつつ GUI/CLI で「全ページ合成に失敗したため選択ページのみ出力した」と明示する（黙って抜粋にしない）。

### 4.3 本体の呼び出し方
PyInstaller での単一バンドル化を前提とするため、**subprocess ではなくインプロセス呼び出し**:

```python
import sys
sys.path.insert(0, str(UPSTREAM_SRC_DIR))  # external/ndlocr-lite/src
import ocr  # noqa: E402
from argparse import Namespace

args = Namespace(
    sourcepdf=str(tmp_pdf),
    sourcedir=None, sourceimg=None,
    output=str(out_dir),
    pdf_output=(str(out_pdf) if out_pdf else None),  # NOTE: `str(x) or None` は誤り（"None"文字列が truthy）
    pdf_render_dpi=dpi,
    pdf_visible_text=False,
    viz=False, json_only=False,
    simple_mode=False, device="cpu",
    enable_tcy=tcy_enabled,  # GUI トグル（既定 False）。tcy_* は未設定でよい（既定値が効く）
    # det/rec の重み・クラスは必ず model_dir()/config_dir() から組み立てて明示設定する。
    # ocr.py の argparse 既定（__file__ 基準）には依存しない（凍結時に非ASCIIパスになるため／§4.4・§6.1）。
    ...
)
ocr.process(args)  # ← 参考例。実際の通常経路ではこれを呼ばない（下の注記）
```

> **このコードブロックは `Namespace` の組み立て例**であり、末尾の `ocr.process(args)` は呼び出しの概念図にすぎない。**通常経路では `process()` を呼ばず、`runner.py` が下位関数（§4.3 補足）経由で一貫して実行する**（§4.2 手順3 で一本化）。`Namespace` に渡す全フィールドは `ocr.py:main()` の `add_argument` を網羅すること（下位関数も `getattr(args, ...)` でこれらを参照する）。

> **図中テキスト対応（§4.5）のための補足**: 図領域 OCR は本体トップレベルの `ocr.process(args)` だけでは実現できない（process は per-page 画像も検出結果も返さない）。したがって `runner.py` は `process_pdf_documents` の制御・シリアライズ部分を担い、同じく `ocr` モジュールの**下位関数を直接再利用**する: `ocr.get_detector(args)` / `ocr.get_recognizer(args, weights_path=...)` / `ocr._run_ocr_on_image_array(...)` / `ocr.embed_text_layer_pdf(...)`。これらは module-level の公開関数で、**上流ファイルを編集せず import して呼ぶだけ**（§2「アルゴリズム改変はしない」と矛盾しない）。`_run_ocr_on_image_array` は先頭 `_` だが上流の実体関数であり、改変せず利用する前提でこれに依存する（§4.1 の「上流改変なし」を維持。万一 1.2.3 以外で消滅・改名されたら §4.1 に従い対処）。

### 4.4 コンポーネント構成
```
src/                         # 本アプリのコード（上流とは別）
├─ app.py                    # 単一エントリ。引数で GUI/ヘッドレスを分岐（flet pack の対象）
├─ cli.py                    # ヘッドレス処理本体（app.py が --cli 時に呼ぶ。GUI 非依存）
├─ pagespec.py               # ページ式パーサ
├─ pdfslice.py               # pypdf によるページ抽出 → 一時PDF
├─ pdfmerge.py               # 全ページ保持の合成（§4.2a。元PDF全ページ＋選択ページのテキスト層）
├─ figocr.py                 # 図領域の追加OCR（§4.5。上流検出器/認識器を再利用）
├─ runner.py                 # 上流 ocr の関数を呼ぶドライバ（GUI 非依存。§4.2a/§4.5 を統括）
├─ paths.py                  # 同梱モデル/設定/上流 src の解決（PyInstaller 対応）
└─ _version.py               # 既定 "0.0.0+dev"（コミット）。CI がタグから上書き
tests/fixtures/sample.pdf            # OCR 可能な日本語・8ページ以上の PDF（コミット。#2/#3/スモーク兼用）
tests/fixtures/sample_with_figure.pdf # 図（block_fig 等）の中に日本語テキストを含む PDF（コミット。§4.5 の図OCR検証用）
external/ndlocr-lite/        # git submodule（UPSTREAM_REF で固定、改変なし）
.gitmodules                  # submodule 定義
```

**単一バイナリと起動分岐（High1 対応）**: `flet pack` が梱包するエントリは **`app.py` 一つ**。`app.py` は起動直後に引数を見て分岐する:
- `--cli`（+ 入力 PDF・ページ等）が在れば、Flet を起動せず `cli.py` のヘッドレス処理を実行して終了コードを返す。
- 引数が無ければ通常どおり `ft.app(target=main)` で GUI を起動。

これにより GUI exe と CLI exe を分けずに済み、§7.2 のスモークテストは同じ exe を `<exe> --cli tests/fixtures/sample.pdf --output ...` で起動できる。

**レイヤ分離（重要）**: `runner.run(input_pdf, pages, *, dpi, enable_tcy, make_searchable, keep_all_pages=True, ocr_figures=True, out_dir, progress=None) -> OcrResult` は **GUI に一切依存しない純関数**。`app.py` の GUI 経路と `cli.py` のヘッドレス経路の両方がこれを呼ぶ。`progress` は任意コールバックで、GUI はこれ経由で進捗を受け取る。
- `keep_all_pages`（既定 `True`）: §4.2a の全ページ保持出力。`False` で従来の抜粋のみ。`pages=None`（全ページ）のときは無視（結果同一）。
- `ocr_figures`（既定 `True`）: §4.5 の図領域 OCR。`False` で従来どおり図をスキップ。

#### `paths.py` のインタフェース契約（点5対応）
開発時（`external/ndlocr-lite/src/`）と PyInstaller/flet pack 実行時（`sys._MEIPASS` 下）の両方で同一 API を返すこと。最低限以下を実装する:

```python
def upstream_src_dir() -> Path: ...   # ocr.py / deim.py のあるディレクトリ
def model_dir() -> Path: ...          # *.onnx のあるディレクトリ
def config_dir() -> Path: ...         # ndl.yaml / NDLmoji.yaml のあるディレクトリ
def ensure_upstream_importable() -> None:
    # upstream_src_dir() を sys.path 先頭に挿入し、
    # `from deim import DEIM` 等の相対 import を成立させる。冪等に。
def ascii_workspace() -> Path:
    # 保証された ASCII パスの作業ディレクトリを返す（§6.1）。
    # エンジンに渡す PDF/モデル/出力はすべてこの配下に置く。
```
- 解決順: PyInstaller 凍結時は `sys._MEIPASS` 起点、非凍結時は `external/ndlocr-lite/src` 起点。
- `runner.py` は `ocr` を import する前に必ず `ensure_upstream_importable()` を呼ぶ。
- `Namespace` の det/rec 重み・クラスパスは `model_dir()` / `config_dir()` から組み立てて明示的に渡す（`__file__` 基準の既定に暗黙依存しない）。
- `model_dir()` は §6.1 の方針に従い、**非 ASCII を含まないパス**を返すこと（必要なら ASCII キャッシュへモデル/設定を複製してそのパスを返す）。

### 4.5 図領域内テキストの OCR（必須・既定 ON）
本体は図（`block_fig`=6 等）の中の文字を認識しない（§3 既知の制約）。検出器は図をブロックとして検出するが、認識（`process_cascade`）は `LINE` 要素にしか走らないため、出力 PDF の図部分にテキスト層が乗らない。これを本アプリで補う。**上流ファイルは編集せず**、上流の検出器・認識器・テキスト層関数を import して再利用する（§4.3 補足）。

対象クラス（`config/ndl.yaml`）: **`6: block_fig` / `11: block_chart` / `15: block_table`**（既定。図・チャート・表）。`12: block_eqn` 等を含めるかは実装時に fixture で判断（既定の集合は上記3つ）。

**方式（主案）— 図領域クロップの再OCR**:
1. 各ページのレンダリング画像（§4.2 の経路で pypdfium2 が作る `np.ndarray`）に対し、`ocr.get_detector(args).detect(img)` で検出を取得し、`class_index ∈ {6,11,15}` のボックスだけ抽出する。
2. 各図ボックスでページ画像をクロップし、**`ocr._run_ocr_on_image_array(...)` をそのクロップに対して単独画像として実行**する。クロップ内では図全体が「ページ」になるため、本文検出と同じ要領で内部の文字行が `LINE` として検出・認識されることを狙う。
3. 認識された各行の座標を**ページ全体座標へオフセット復元**（クロップ原点 `(xmin,ymin)` を足す）し、そのページの `text_layer_lines` に**追記**する。`.txt`/`.json` にも図由来テキストを足す。**重複防止**: 図クロップで得た行が、基盤パイプラインが既に検出した行（`text_layer_lines`）と所定割合以上重なる場合は追加しない（base が読めた図内テキストを二重計上しない）。**`.xml`（`page_xml`）には図由来テキストを加えない**——基盤検出の構造をそのまま保ち、上流の XML 形式との一致を崩さないため（#12c の XML パリティは図OFF で検証する。図ONで `.xml` に出ないのは仕様）。
4. 追記後の `page_results` で `ocr.embed_text_layer_pdf(...)` を呼んでテキスト層 PDF を生成する（§4.2a の全ページ保持合成より前段）。

**実装時の必須検証（fail-fast。これが「スパイク」の代わり）**: `tests/fixtures/sample_with_figure.pdf`（図中に既知の日本語テキストを含む）で、図OCR ON のとき**その既知テキストが出力 `.txt`／検索可能 PDF のテキスト層に現れる**ことを自動テストで確認する。現れなければビルド/テストを fail させる。

**主案が不十分だった場合のフォールバック（検証で判明したら順に適用）**:
- (a) 図クロップに対してのみ検出閾値を下げる。`args` をクロップ用に複製して `det_score_threshold`/`det_conf_threshold` を下げ、**その `crop_args` で `ocr.get_detector(crop_args)` を作り直した検出器**を `_run_ocr_on_image_array(...)` に渡す（同関数は `args` ではなく生成済み detector を受け取るため）。ページ全体用の detector は変更しない。
- (b) クロップを拡大（高 DPI で再レンダリング）してから再OCRする。
- (c) (a)(b) でも図中テキストが取れないことが構造的に確定した場合のみ、§4.1 に従い「上流改変が必要 → fork へ切替」を**未決事項に戻して**判断する。必須要件なので要件自体は下げない。

**性能・既定**: 図が多い文書では検出+再OCRの追加コストがかかる。既定 ON だが、GUI チェック／CLI `--no-ocr-figures` で無効化できる（§5.1・§5.4）。進捗表示は図OCR中も `progress` に流す（「図を処理中 k/n」等）。

**全ページ保持（§4.2a）との順序**: 図OCR はテキスト層生成より前（手順2〜3で `page_results` を増やす）。全ページ保持の合成（§4.2a）はテキスト層 PDF 生成後のページ差し替えなので、図OCR の結果はそのまま全ページ保持 PDF にも反映される。

---

## 5. 機能要件

### 5.1 GUI
- フレームワーク: **Flet（確定）**。`flet==0.27.6` 固定。
- **入力手段の決定（D&D 検証結果）**: Flet 標準の Draggable/DragTarget は**アプリ内 D&D 専用で、Explorer からの OS ファイルドロップには使えない**。OS ファイルドロップは 3rd-party 拡張 `flet-dropzone`（Flutter の `desktop_drop` ラッパー）が必要だが、これは **Flutter プラグインなので `flet build`（Flutter SDK + VS）必須**＝§7 の `flet pack` 方針と衝突する。
  - **v1 の必須入力は `FilePicker`（「PDF を選ぶ」ボタン）**。`flet pack` で確実に動き、当初要件「ドラッグ**か**開く」の「開く」を満たす。非技術者向けには大きな選択ボタンで十分。
  - **OS ドラッグ&ドロップは任意・要検証（verified-risk）**。採用するなら別途スパイクで `flet-dropzone` を検証し、かつビルドを `flet build` に切り替える判断が要る（§7 の方針変更を伴う）。v1 ではドロップ非対応でも可とする。
- エントリは `app.py`。引数なしで `ft.app(target=main)` を起動、`--cli` 指定時は Flet を起動せずヘッドレス処理（§4.4）。`flet pack` には `app.py` を渡す。
- 画面要素:
  - **「PDF を選ぶ」ボタン（`FilePicker`）= 必須の入力経路**。ドロップ領域は採用できた場合のみの追加 UI。
  - ページ指定入力欄（空欄＝全ページ）。プレースホルダ例 `例: 1,3,5-8`
  - DPI 指定（既定 150、上級者向けに折りたたみで可）
  - 「検索可能 PDF を作る」チェック（既定 ON）
  - 「指定ページだけ OCR しても全ページを残す」チェック（**既定 ON**）。`runner.keep_all_pages` に直結（§4.2a）。OFF で選択ページだけの抜粋 PDF。ページ未指定時はグレーアウト（効果なし）。
  - 「図の中の文字も読む」チェック（**既定 ON**）。`runner.ocr_figures` に直結（§4.5）。図が多い文書では時間が延びる旨を補助テキストで添える。
  - 「縦中横（縦書き資料向け）」チェック（**既定 OFF**）。`Namespace.enable_tcy` に直結。
  - 実行ボタン、進捗表示（`runner` がページループを統括し、各ページの本文OCR・図OCRの開始/完了時に `progress` コールバックを直接呼ぶ。GUI はそれを受けてバー/ラベルを更新。例: `OCR PDF page i/n`、`図を処理中 k/n`。§10 解決済みメモ参照）
  - 完了後に出力フォルダを開くボタン
- **OCR は UI スレッドで実行してはならない（ブロッカー2）**。`runner.run(...)` の OCR は数秒〜数分の CPU 処理で、Flet の `target=main` スレッドで直接呼ぶとウィンドウが固まり「応答なし」になる。`runner.run(...)` を**バックグラウンドスレッド/executor で実行**し、実行ボタンは処理中無効化、進捗・完了は `progress` コールバック経由で受けて UI スレッドに marshal（`page.update()`）する。これは必須要件。
- Namespace へのマッピング（曖昧さ排除）:
  - 「検索可能 PDF を作る」: エンジンは検索可能 PDF を**常に生成する**（`embed_text_layer_pdf` を無条件に呼ぶため、上流改変なしには抑止できない）。チェック OFF の場合は**生成後にその `_text.pdf` を削除**して実現する。
  - `json_only` は常に `False`（.txt/.xml/.json を出すため）。UI には出さない。
  - 「縦中横」→ `enable_tcy`、DPI → `pdf_render_dpi`、「全ページ残す」→ `keep_all_pages`、「図の中の文字も読む」→ `ocr_figures`。
- 縦中横の実装メモ: `enable_tcy=True` を立てるだけでよい。`ocr.py` は `tcy_*` 引数のうち None でないものだけを拾い、`TateChuYokoWrapper` が全パラメータに既定値を持つため、`tcy_*` を `Namespace` に設定しなくても既定値で動作する（PDF 経路の recognizer にも適用される）。詳細な tcy パラメータの UI 露出は将来拡張とし、当面はトグルのみ。
- 出力先: 既定で「入力 PDF と同じフォルダ内の `<元stem>_ocr/`」。ユーザーが変更可能（§4.2 手順4でここへ移動・リネーム）。

### 5.2 ページ式パーサ（`pagespec.py`）
- シグネチャ: `parse_pages(spec: str, total: int) -> list[int] | None`
- 入力: `"1,3,5-8"` のような文字列
- 出力: 昇順・重複排除した **1-based** ページ番号 `list[int]`
- **全ページの番兵は `None`**（空文字・空白のみの入力は `None` を返す）。`pdfslice.py` 側は「`None` なら抽出をスキップし元 PDF をそのまま渡す」「`list[int]` なら該当ページを抽出」で分岐する。空 list は返さない（誤って全 PDF を処理する事故を防ぐため、0 ページ指定は後述のエラー扱い）。
- 仕様:
  - カンマ区切り、`a-b` は閉区間
  - 空白は無視
  - 総ページ数 `total` を渡し、範囲外・逆順・非数値・結果が 0 件は明確なエラー（例外）で弾く
- 単体テストを必ず付ける（正常系 + 異常系: `5-2`, `0`, `999`, `a`, 末尾カンマ, 空文字→`None` 等）

### 5.3 ページ抽出（`pdfslice.py`）と作業ディレクトリ片付け
- `pypdf.PdfReader` で読み、`PdfWriter` に選択ページを追加し、§4.2 の ASCII 作業ディレクトリに `doc.pdf` として書き出す。
- 暗号化 PDF は**空パスワードで開けるもののみ**対応。判定は `is_encrypted` だけでなく、空文字での復号 `reader.decrypt("")` が成功するかを実ゲートとする（空パスワード暗号化があるため）。開けない場合は明示エラー。
- **削除のタイミング規約（ブロッカー4）**: Windows では pypdfium2 がレンダリング中に PDF ハンドルを保持する。`runner` の本文OCR（各ページの `_run_ocr_on_image_array` ループ）・図OCR（§4.5）・テキスト層 PDF 生成（`embed_text_layer_pdf`）・全ページ保持合成（§4.2a）といった**作業ディレクトリ内ファイルに触る処理がすべて完了（return）した後**にのみ作業ディレクトリを削除すること。`finally:` でストリーム途中に `unlink` してはならない（`PermissionError [WinError 32]` になる）。全ページ保持合成のため、原本 PDF（`orig.pdf`）も合成完了まで作業ディレクトリに保持する。
- 片付けは作業ディレクトリ単位で行い、ロック残存に**耐性を持たせる**: `shutil.rmtree(ws, ignore_errors=True)`、または短いリトライ（数百 ms × 数回）。削除失敗でユーザー向け処理を失敗させない（次回起動時の掃除でも可）。

### 5.4 CLI 契約（`app.py --cli` / `cli.py`）
GUI と同じ `runner.run(...)` を叩くヘッドレス経路。CI スモークテスト・自動化・受け入れ #2/#3 が依存するので契約を固定する。

```
<exe> --cli <INPUT.pdf> [--pages 1,3,5-8] [--output DIR] [--dpi 150]
                        [--enable-tcy] [--no-searchable-pdf] [--excerpt-only]
                        [--no-ocr-figures] [--no-clobber] [--quiet]
```
- `INPUT.pdf`（位置引数・必須）: 入力 PDF。
- `--pages`（任意・既定 全ページ）: §5.2 の式。範囲外等はエラー終了。
- `--output DIR`（任意・既定 `<入力と同フォルダ>/<元stem>_ocr/`）。
- `--dpi FLOAT`（任意・既定 150）→ `pdf_render_dpi`。
- `--enable-tcy`（任意・既定 OFF）→ `enable_tcy`。
- `--no-searchable-pdf`（任意）: 検索可能 PDF を残さない（生成後に `_text.pdf` を削除。§5.1 と同挙動）。既定は残す。
- `--excerpt-only`（任意・既定 OFF）: `--pages` 指定時、全ページ保持をやめて**選択ページだけの抜粋 PDF**を出す（§4.2a）。既定は全ページ保持（`keep_all_pages=True`）。`--pages` 無指定時は無効。
- `--no-ocr-figures`（任意・既定 OFF）: 図領域 OCR（§4.5）を無効化する。既定は有効（`ocr_figures=True`）。
- `--no-clobber`（任意）: 出力先が既存なら上書きせず `<元stem>_ocr_YYYYMMDD-HHMMSS/` に退避（§4.2 手順4）。既定は上書き。
- `--quiet`（任意）: 進捗行を抑制。
- **終了コード**: `0`=成功、`2`=引数/使用法エラー、`3`=入力 PDF を開けない/空パスワード復号失敗（§5.3）、`1`=その他処理エラー。
- **stdout/stderr**: 進捗（`[INFO] OCR PDF page i/n` 由来）は stdout、エラーメッセージは stderr。`--cli` 経路では `redirect_stdout` を使わず素通しでよい（GUI 経路のみ §10 の捕捉を行う）。
- スモークテスト（§7.2）の呼び出し例: `<exe> --cli tests/fixtures/sample.pdf --output <tmp>`。

---

## 6. 非機能要件
- 対象 OS: **Windows 11**（10 でも動けば望ましい）
- 起動からファイル選択までに Python/pip/git のインストールを要求しない
- 1 ページあたり CPU で数秒〜十数秒を許容（本体性能依存。アプリ側で速くしようとしない）
- 同梱物のサイズは数百 MB を許容
- エラーは GUI 上で日本語の平易なメッセージとして提示（スタックトレースを生で出さない）

### 6.1 非 ASCII パス耐性（必須・ブロッカー1）
対象ユーザーの既定パスは `C:\Users\<日本語名>\Desktop\...` のように非 ASCII を含む。上流は非 ASCII パスで起動失敗することがあるため、**「ASCII フォルダに置いてください」という README 注記では対象ユーザーを救えない**。以下を要件とする。

根本原因は2系統（実装時に要再現・切り分け）:
1. **DLL/モデルの読み込みパスが非 ASCII**（アプリ自身が非 ASCII フォルダに展開された場合）。onnxruntime/pypdfium2 の DLL ロードや `.onnx` 読み込みが失敗しうる。
2. **エンジンに渡す作業パスが非 ASCII**（入力 PDF・出力先）。

対策（層で守る）:
- **(A) 作業経路は常に ASCII**: §4.2/§4.4 の通り、エンジンへ渡す PDF・モデル・出力は `ascii_workspace()` 配下の ASCII パスに限定。`model_dir()` は非 ASCII なら ASCII キャッシュへ複製して返す。→ 原因2 を解消。
- **(B) ASCII への自己再配置（必須）**: 非 ASCII 支援は対象ユーザーにとって中核要件であり妥協できない（受け入れ #8・README 約束と一致させる）。起動時に自身の配置パスが非 ASCII なら、固定 ASCII ベース（例 `C:\Users\Public\ndlocr-pdf\`。ユーザー名に依存せず ASCII）へ payload を複製して再起動する軽量ランチャを**必ず実装する**。複製は冪等（後述のキャッシュ規約）。
- **(C) 最終安全網**: ASCII ベースへの書き込みすら不能（権限皆無等の極端な環境）な場合に限り、移動先候補を示す日本語ダイアログを出して終了。これは (B) の代替ではなく、(B) が物理的に不可能なときの最後の砦。
- **要件の不可侵性**: 「非 ASCII パスでも起動し OCR が完了する」(#8) は必達。実機検証で (B) だけでは不足と判明した場合は、要件を下げるのではなく**真の故障点を追って解決する**（原因1 が DLL ロード段で (B) でも残るなら、ASCII 再配置先からの起動を確実にする等）。要件と README とアクセプタンスは常に同じ強さに保つ（片方だけ弱めない）。

#### キャッシュ/再配置の規約（Medium6・(A) のモデルキャッシュと (B) の再配置に共通）
数百 MB を複製しうるため以下を満たす:
- **バージョン鍵**: 複製先はバージョン込みのパス（例 `...\ndlocr-pdf\<__version__>\`）。バージョン不一致なら作り直す。
- **完了マーカー**: コピーは一時ディレクトリへ行い、**全コピー成功後に rename**（アトミック）。完了時にセンチネル（例 `.complete`）を最後に書く。起動時はセンチネル有無で「使えるキャッシュか」を判定し、部分コピー（前回中断）は無効として作り直す。
- **同時起動ロック**: 初回複製中に二重起動されても壊れないよう、複製はロック（ロックファイル/ミューテックス）で直列化する。待機側は完了後に既存キャッシュを使う。
- **古い版の掃除**: 旧バージョンのキャッシュは起動時に削除（任意だがディスク肥大防止のため推奨）。

> 検証は §9 受け入れ基準 #8（日本語を含むパスでの起動+OCR）で担保する。

---

## 7. パッケージング / ビルド（決定事項）

- 方式: **`flet pack`（確定）**。中身は PyInstaller だが Flet クライアント（Flutter 製 GUI バイナリ）の同梱を自動で行う。`--add-data` / `--add-binary` / `--hidden-import` / `--icon` など PyInstaller 同等のオプションがそのまま使える。
  - 素の PyInstaller 直叩きは Flet クライアント同梱が脆いため不可。`flet build`（Flutter SDK + Visual Studio C++ ワークロードが必要）は本用途には過剰なため不可。
  - 既定でバンドル（フォルダ）出力。`--onefile` 相当は起動が遅く誤検知されやすいので使わない。
- ビルド環境: **Windows 上でビルド**（クロスコンパイル不可）。手元 Ubuntu からは作れない。必要なのは Python + flet + PyInstaller のみ（Flutter/VS は不要）。
- CI: **GitHub Actions の `windows-latest` ランナー**でビルドし、成果物を本リポジトリの releases に添付。上流の `.github/workflows` を参考にする。
  - `actions/checkout` で `submodules: recursive` を指定し、ビルド前に submodule（モデル含む）を必ず取得すること。
- 同梱データ（`flet pack --add-data`、Windows ビルドなので区切りは `;`）:
  - **`external/ndlocr-lite/src/` を一式同梱するのみ**。`ocr.py` は `base_dir = Path(ocr.py).parent` 基準で `model/`・`config/` を解決するので、`src/` を丸ごと入れれば `model/`・`config/` も含まれる。`model/`・`config/` を個別に追加してはならない（ONNX を二重梱包し、PyInstaller の重複警告とサイズ倍増を招く）。
  - 配布先で `model/`・`config/` が `ocr.py` と同じ相対位置に並ぶことを確認する。
- ネイティブ依存の取りこぼし対策: `onnxruntime` / `pypdfium2` は `--hidden-import` もしくは `--collect-all`（onnxruntime）で明示的に拾えているかを、後述の**スモークテストで自動検証**する（目視確認はしない）。
- `paths.py` は PyInstaller 実行時の `sys._MEIPASS` と通常実行の双方でモデル/設定/上流 src を解決できること。
- README は「**日本語（全角）を含むパスに置いても動作する**」と明記する（§6.1 で対応を必達とするため。「全角パスに置くな」とは書かない）。万一 §6.1 (B) を実装段階で断念する場合のみ、この方針と §6.1 を同時に格下げすること（片方だけ弱めて矛盾させない）。
- リスク: `flet pack` は `flet build` に置換される旧コマンド扱い。0.27.6 固定では動作するが、将来 flet を上げると消える可能性がある。flet を上げる際は `flet pack` の存続を確認し、無ければ `flet build`（重いツールチェイン）への移行を検討する。

### 7.1 リリース運用 / CI トリガ
- バージョニング: **semver**。リリースは `vMAJOR.MINOR.PATCH` 形式の **git タグで駆動**。`project.version`（pyproject）はタグから注入する。
- CI トリガ: `on: push: tags: ['v*']`。タグ push → `windows-latest` でビルド → スモークテスト通過 → zip を GitHub Releases に添付。
- 日常の push/PR では lint + 単体テスト（`pagespec` 等）のみ。重いパッケージングはタグ時のみ。
- タグを打つのはメンテナ（手動）。`main` への自動リリースはしない。
- **バージョン注入の実体（gap6）**: `flet pack`/PyInstaller は git タグを読まない。CI のビルド前ステップで、タグ名 `${{ github.ref_name }}`（先頭 `v` を除去）を `src/_version.py`（例 `__version__ = "1.2.0"`）へ書き出し、`pyproject.toml` の version もこれに合わせる。アプリは `_version.py` を import して表示に使う。`pyproject` に literal で固定しない（§0 の `0.1.0` は開発初期値のプレースホルダ）。
  - **開発時フォールバック（point3）**: 既定の `src/_version.py`（`__version__ = "0.0.0+dev"`）を**リポジトリにコミット**しておき、CI はこれを上書きする。これにより素の dev チェックアウトでも `from _version import __version__` が壊れない（import を try/except で包むのでも可）。

### 7.2 ビルド後スモークテスト（自動）
CI のパッケージング後、生成 exe を実起動して以下を検証し、いずれか失敗でジョブを fail させる:
- リポジトリ同梱の `tests/fixtures/sample.pdf`（複数ページ）を、**生成 exe を `<exe> --cli` で起動**して OCR 実行（§4.4 の起動分岐。GUI は起動しない）。スモークは全ページでも `--pages 1` でも可。
- プロセス終了コードが `0`
- 期待する出力（`*.txt` と検索可能 `*_text.pdf`）が生成されている
- これにより onnxruntime/pypdfium2/モデルの同梱漏れ（凍結後にのみ顕在化する不具合）を機械的に検出する。

---

## 8. ライセンス遵守（必須）

### 8.1 結論: モデル・DLL 同梱配布は可能
`LICENCE_DEPENDENCEIES` を確認した結果、同梱対象はすべて寛容ライセンスで、**ONNX モデルと onnxruntime 等のネイティブバイナリを exe に同梱して公開配布して差し支えない**:
- NDLOCR-Lite 本体 + `*.onnx` モデル: **CC BY 4.0**（帰属表示で再配布可）
- 依存: dill / numpy / networkx / protobuf / lxml = **BSD**、flet / onnxruntime(MIT) / parseq / deimv2 / reportlab = **Apache 2.0 / MIT / BSD**、opencv-python-headless = **Apache 2.0**、pypdf = **BSD**、pypdfium2 + 同梱 **PDFium = BSD-3**、Pillow = **HPND**、tqdm = **MPL-2.0**
- **GPL/AGPL は無し**。tqdm の MPL-2.0 はファイル単位コピーレフトのみで、未改変同梱なら通知保持だけで OK。PDFium は初回リリース前に念のためライセンス本文を確認する。
- 上記は概観で網羅ではない。**正は §8.2 の `uv.lock` 由来生成物**。
- （注: 法的助言ではない。配布前に各ライセンス本文を一読のこと。）

### 8.2 配布物に含める表示
- `NOTICE`（または `licenses/`）に、(1) NDL の CC BY 4.0 帰属表示と原典リンク、(2) 自分の変更点（「ページ指定 GUI ラッパーを追加」等）、(3) 依存ライセンス全文、を同梱する。
- (3) は手書きリストにせず、**解決済みの `uv.lock` から機械生成する**（例: `uv export` + ライセンス収集ツール）。§8.1 のライセンス列挙はあくまで概観で、tqdm 等を含む正は `uv.lock`。手書きだと submodule/依存更新で静かにズレるため、生成を CI 工程に組み込む。
- 自作部分のライセンスは任意（CC BY は share-alike ではない）。ただし上流由来部分の表示は維持する。
- CI のパッケージング工程で `NOTICE` を配布 zip に確実に含める。

---

## 9. 受け入れ基準（Acceptance criteria）
各項目に [auto]=CI で自動検証 / [manual]=手動・実機検証 を付す。**[auto] が緑でも全体の合格ではない**（CI は非ASCIIユーザープロファイルや起動体験を完全には再現できない）。

1. [manual] クリーンな Windows（Python 未インストール）で、解凍 → ダブルクリック → 起動できる
2. [auto] `--cli` 経由で複数ページ PDF を OCR すると、ページ未指定で全ページ処理され txt/xml/json と検索可能 PDF が出る
2b. [manual] GUI でドラッグ&ドロップ（または「開く」）して同じ結果になる（UI 自動化が使えるなら Playwright 等で auto 化可）
3. [auto] `--cli` で `1,3,5-8` 指定すると**そのページだけが OCR 処理**される（`.txt/.json` は当該ページ分のみ）
3b. [auto] **全ページ保持（既定）**: 上の指定で出る検索可能 PDF が**元PDFの全ページ数を保ち**、選択ページ（1,3,5-8）にのみ新しいテキスト層が載ることを検証する。非選択ページは、出力の抽出テキストが入力PDFから増えていないことを比較する（入力PDF自体がデジタルテキストを持つ場合があるため、「抽出テキストが空」は要求しない）。可能なら `sample.pdf` はラスタ化済み・埋め込みテキストなしの fixture とし、その場合は非選択ページの抽出テキストが空であることも検証する（§4.2a）
3c. [auto] **抜粋モード**: `--excerpt-only` を付けると検索可能 PDF が**選択ページだけ**になる（従来挙動・§4.2a）
4. [manual] 異常なページ式で分かりやすいエラーが GUI に出る（クラッシュしない）
5. [auto] `pagespec` の単体テストが全て通る
6. [manual] 出力フォルダを開くボタンが機能する
7. [auto] CI のビルド後スモークテスト（§7.2）が通る（exe が `sample.pdf` を終了コード 0 で OCR し、txt と検索可能 PDF を出力）
8. [auto一部/manual] **日本語を含むパス**で起動し OCR が完了する。日本語名フォルダに**展開して実行**する経路は CI でも再現可（`C:\テスト\` 等）。非ASCIIな**ユーザープロファイル**（`C:\Users\田中\...`、`%TEMP%` も非ASCII）は windows-latest が ASCII ユーザーのため手動/VM 検証（§6.1）
9. [manual] OCR 実行中もウィンドウが応答し続け、進捗が更新される（フリーズ・「応答なし」が出ない／§5.1 ブロッカー2）
10. 出力ファイル名が**入力 PDF の名前**になっている（temp 名で出力されない／§4.2 ブロッカー3）
11. [auto] **図中テキストの OCR（§4.5）**: `tests/fixtures/sample_with_figure.pdf` を図OCR ON（既定）で処理すると、図の中の既知テキストが出力 `.txt` と検索可能 PDF のテキスト層に現れる。`--no-ocr-figures` 指定時は現れない（=切替が効く）。図OCR が空振りする場合はビルド/テストを fail させる（必須機能のため）
12. [auto] **runner 一本化の drift 検知（§4.2 手順3）**: 以下の3テストを備える。submodule 更新で壊れたら fail する。
    - (a) **出力契約テスト**: runner が出す `.txt/.xml/.json` を自前のゴールデンファイルと突き合わせ、我々の出力形式を固定する。
    - (b) **上流内部APIガードテスト**: 再利用する上流下位関数の契約を assert する——`_run_ocr_on_image_array(...)` の戻り値 dict に期待キー（`text_layer_lines`/`img_width`/`img_height`/`json_lines`/`text` 等）が揃うこと、`get_detector`/`get_recognizer`/`embed_text_layer_pdf` の署名が想定どおりであること。内部APIが変わったらここで気づく。**ただし (b) はシグネチャと戻り値キーしか見ないため、同じ API のまま XML/JSON の意味・整形が変わる drift は捕まえられない。それは (c) で担保する。**
    - (c) **パリティテスト（`UPSTREAM_REF` 更新 PR では必須）**: 上流 `ocr.process()` を `sample.pdf` に走らせた出力と、runner（図OFF・同一 DPI/設定・同一入力）の出力を突き合わせ、基盤パイプラインを忠実に再現していることを確認する。(a)(b) では捕まらない意味的 drift（XML/JSON の構造・整形の変化）を検出する本丸。
      - **比較対象**: `.txt` だけでなく、**可変値を正規化した `.xml` と `.json` も含める**。正規化で吸収する可変値: 入力 PDF パス/名（`pdf_path`/`pdf_name`/`img_path`/`img_name`）、出力 stem（上流は元 stem・runner は `doc` 等）、絶対パス、（あれば）タイムスタンプや実行時間。座標・テキスト・クラス・ページ構造は正規化せず**そのまま一致を要求**する。
      - **実行ゲート**: フル OCR で重いので毎コミットでは任意（手元/夜間で可）。**`external/ndlocr-lite` の gitlink もしくは `UPSTREAM_REF` を変更する PR では CI 必須**とし、submodule 更新時に意味的 drift があれば必ず fail させる（§4.1 の submodule 更新規律と対）。

---

## 10. 未決事項（実装前に確認）
1. 出力既定フォルダの命名規則（`<元stem>_ocr/` でよいか。実装中に確定でよい軽微事項）
2. 図OCR（§4.5）の対象クラス集合の最終確定。既定は `block_fig`/`block_chart`/`block_table`（6/11/15）。`block_eqn`(12) 等を含めるかは `sample_with_figure.pdf` での検証で決める。**機能自体は必須・既定 ON で確定**（未決なのは対象クラスの範囲のみ）。
3. 図OCR の主案（領域クロップ再OCR）が fixture で空振りした場合の確定対応（§4.5 フォールバック (a)→(b)→(c)）。(c)（上流 fork）に至るのは構造的に不可能と判明したときのみで、その場合は §4.1 に従い改めて判断する。

> 解決済み（旧 #1・進捗表示）: `runner.py` は §4.2/§4.3 のとおりページループを統括するため、各ページのレンダリング・本文OCR・図OCRの開始/完了時に**直接 `progress` コールバックを呼ぶ**（例: `OCR PDF page i/n`、`図を処理中 k/n`）。上流 `ocr.py` の `process_pdf_documents` が出す `print(f"[INFO] OCR PDF page i/n: ...")` は利用しない。これによりプロセス全体に影響する `contextlib.redirect_stdout` は不要であり、GUI スレッドでの `print` との競合もない。総ページ数は §4.2 手順1で取得済みなので i/n を確定値で出せる。

---

## 付録 A: ocr.py:main() の全引数（tag 1.2.3 実測・権威リスト）

> README は不正確なので使わない。下記は tag **1.2.3** の `ocr.py:main()` の `add_argument` を**全て**列挙したもの（抜粋ではない）。`Namespace` はこの全キーを `process()`/`process_pdf_documents()` 内の `getattr(args, ...)` 参照に対し過不足なく満たすこと（欠落は `process()` 深部で `AttributeError` として表面化する）。実装時は 1.2.3 の `ocr.py` で再確認すること。

| 引数 (dest) | 型 / 既定 | 備考 |
|---|---|---|
| `sourcedir` | str / None | 画像ディレクトリ（本アプリでは未使用） |
| `sourceimg` | str / None | 画像単体（未使用） |
| `sourcepdf` | str / None | **PDF 入力（本アプリで使用）** |
| `output` | str / **必須** | 出力ディレクトリ |
| `viz` | bool / False | 可視化画像出力 |
| `pdf_output` | str / None | 検索可能 PDF の出力先（未指定なら `<stem>_text.pdf`） |
| `pdf_render_dpi` | float / 150.0 | レンダリング DPI（`--pdf-dpi` 別名） |
| `pdf_visible_text` | bool(store_true) / False | デバッグ用に青字でテキスト層を可視化 |
| `det_weights` | str / 既定パス | 下表参照 |
| `det_classes` | str / 既定パス | 下表参照 |
| `det_score_threshold` | float / 0.2 | |
| `det_conf_threshold` | float / 0.25 | |
| `det_iou_threshold` | float / 0.2 | |
| `simple_mode` | bool / False | 1 モデルで認識 |
| `rec_weights30` | str / 既定パス | 下表参照 |
| `rec_weights50` | str / 既定パス | 下表参照 |
| `rec_weights` | str / 既定パス | 下表参照（**100 系**） |
| `rec_classes` | str / 既定パス | 下表参照 |
| `device` | str / "cpu" | choices: cpu/cuda |
| `enable_tcy` | bool(store_true) / False | 縦中横 |
| `json_only` | bool(store_true) / False | JSON のみ出力（本アプリは False 固定） |

### 重み・設定ファイルの対応（gap5・`model_dir()`/`config_dir()` から組み立てる）

| dest | ファイル |
|---|---|
| `det_weights` | `model/deim-s-1024x1024.onnx` |
| `det_classes` | `config/ndl.yaml` |
| `rec_weights30` | `model/parseq-ndl-24x256-30-tiny-189epoch-tegaki3-r8data-202604.onnx` |
| `rec_weights50` | `model/parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx` |
| `rec_weights` | `model/parseq-ndl-24x768-100-tiny-153epoch-tegaki3-r8data-202604.onnx` |
| `rec_classes` | `config/NDLmoji.yaml` |
