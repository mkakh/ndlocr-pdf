"""Single entry point (§4.4, §5.1).

* ``app.py --cli ...`` -> run the headless pipeline (``cli.main``) and exit.
* ``app.py`` (no args) -> launch the Flet GUI.

This module is what ``flet pack`` bundles. Heavy imports (Flet, the OCR engine)
are deferred so the ``--cli`` path stays light and the GUI import failures don't
break headless use.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

# When run as a plain script (`python src/app.py`), src/ is already sys.path[0].
# When frozen, our modules sit at the bundle root. Be defensive anyway.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths  # noqa: E402

try:
    from _version import __version__
except Exception:  # pragma: no cover
    __version__ = "0.0.0+dev"


def _relocate_guard() -> None:
    """Implement §6.1 (B)/(C): relocate to an ASCII path if needed, else warn."""
    try:
        if paths.relocate_if_needed(sys.argv):
            sys.exit(0)
    except Exception as exc:  # (C) last-resort: cannot relocate to ASCII
        msg = (
            "このアプリは半角英数字のフォルダにコピーしてから実行してください。\n"
            "例: C:\\Users\\Public\\ndlocr-pdf\\\n\n"
            f"詳細: {exc}"
        )
        # No console in GUI mode; try a message box, fall back to stderr.
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, msg, "NDLOCR-PDF", 0x10)
        except Exception:
            print(msg, file=sys.stderr)
        sys.exit(1)


def main_cli() -> int:
    import cli

    argv = list(sys.argv[1:])
    argv.remove("--cli")  # strip the dispatch flag; leave the rest for cli
    return cli.main(argv)


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

def main_gui(page) -> None:
    import flet as ft

    import runner
    from pagespec import PageSpecError
    from pdfslice import PdfOpenError

    page.title = f"NDLOCR-PDF  v{__version__}"
    # Fixed window size (non-resizable): the layout is a simple vertical form.
    page.window.width = 660
    page.window.height = 680
    page.window.resizable = False
    page.window.maximizable = False
    page.padding = 24
    page.scroll = ft.ScrollMode.AUTO

    selected_pdf: dict[str, str | None] = {"path": None}
    last_out_dir: dict[str, str | None] = {"path": None}

    selected_label = ft.Text("PDF が選択されていません", size=14)
    pages_field = ft.TextField(
        label="OCR するページ（空欄＝全ページ）",
        hint_text="例: 1,3,5-8",
        width=320,
    )
    dpi_field = ft.TextField(
        label="読み取り解像度（DPI）",
        value="150",
        width=280,
    )
    # Separate wrapping caption (helper_text would be clipped to the field width).
    dpi_caption = ft.Text(
        "数字が大きいほど精細ですが、処理が遅く・出力も大きくなります。"
        "通常の文書は 150 で十分です。文字が小さい・つぶれ気味の資料は 200〜300 を試してください。",
        size=12,
        color=ft.Colors.GREY,
        width=560,
    )
    searchable_cb = ft.Checkbox(
        label="文字を検索・コピーできる PDF も作る（おすすめ）",
        value=True,
        tooltip="OFF にすると PDF は作らず、テキスト(.txt)などの結果だけ出力します。",
    )
    tcy_cb = ft.Checkbox(
        label="縦書きの資料（新聞・古典籍など）",
        value=False,
        tooltip="縦書き中心の資料で認識精度が上がることがあります（縦中横対応）。"
        "横書きの文書では OFF のままで構いません。",
    )
    progress_bar = ft.ProgressBar(width=560, value=0)
    progress_bar.visible = False
    status_text = ft.Text("", size=14)
    open_folder_btn = ft.ElevatedButton("出力フォルダを開く", icon=ft.Icons.FOLDER_OPEN, disabled=True)
    run_btn = ft.ElevatedButton("OCR 実行", icon=ft.Icons.PLAY_ARROW, disabled=True)
    pick_btn = ft.ElevatedButton("PDF を選ぶ", icon=ft.Icons.UPLOAD_FILE)

    # --- file picker ---
    def on_pick_result(e: "ft.FilePickerResultEvent") -> None:
        if e.files:
            selected_pdf["path"] = e.files[0].path
            selected_label.value = f"選択中: {e.files[0].name}"
            run_btn.disabled = False
        page.update()

    file_picker = ft.FilePicker(on_result=on_pick_result)
    page.overlay.append(file_picker)

    def pick_pdf(_):
        file_picker.pick_files(allow_multiple=False, allowed_extensions=["pdf"])

    pick_btn.on_click = pick_pdf

    # --- progress callback (runs in worker thread) ---
    def on_progress(i: int, n: int, _line: str) -> None:
        progress_bar.value = i / n if n else None
        status_text.value = f"OCR 実行中… {i}/{n} ページ"
        page.update()

    # --- worker ---
    def do_run() -> None:
        try:
            dpi = float(dpi_field.value or "150")
        except ValueError:
            _set_error("読み取り解像度（DPI）は数値で入力してください。")
            _finish()
            return

        try:
            result = runner.run(
                selected_pdf["path"],
                pages_field.value,
                dpi=dpi,
                enable_tcy=tcy_cb.value,
                make_searchable=searchable_cb.value,
                progress=on_progress,
            )
        except PageSpecError as exc:
            _set_error(f"ページ指定が正しくありません。\n{exc}")
            _finish()
            return
        except PdfOpenError as exc:
            _set_error(f"PDF を開けませんでした。\n{exc}")
            _finish()
            return
        except Exception as exc:  # noqa: BLE001
            _set_error(f"処理中にエラーが発生しました。\n{exc}")
            _finish()
            return

        last_out_dir["path"] = str(result.out_dir)
        msg = f"完了しました（{result.page_count} ページ）。\n出力先: {result.out_dir}"
        if result.overwrote:
            msg += "\n（既存の結果を上書きしました）"
        status_text.value = msg
        status_text.color = ft.Colors.GREEN
        progress_bar.value = 1
        open_folder_btn.disabled = False
        _finish()

    def _set_error(message: str) -> None:
        status_text.value = message
        status_text.color = ft.Colors.RED

    def _finish() -> None:
        progress_bar.visible = False
        run_btn.disabled = selected_pdf["path"] is None
        pick_btn.disabled = False
        page.update()

    def start_run(_):
        if not selected_pdf["path"]:
            return
        status_text.value = "OCR 実行中…"
        status_text.color = None
        progress_bar.visible = True
        progress_bar.value = None
        run_btn.disabled = True
        pick_btn.disabled = True
        open_folder_btn.disabled = True
        page.update()
        # OCR must NOT run on the UI thread (§5.1 blocker 2).
        threading.Thread(target=do_run, daemon=True).start()

    run_btn.on_click = start_run

    def open_folder(_):
        path = last_out_dir["path"]
        if path and os.path.isdir(path):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                _set_error(f"フォルダを開けませんでした: {exc}")
                page.update()

    open_folder_btn.on_click = open_folder

    advanced = ft.ExpansionTile(
        title=ft.Text("詳細設定（上級者向け）"),
        controls_padding=ft.padding.only(left=16, right=16, top=4, bottom=16),
        controls=[ft.Column([dpi_field, dpi_caption], spacing=8)],
    )

    page.add(
        ft.Text("PDF を OCR する", size=22, weight=ft.FontWeight.BOLD),
        ft.Row([pick_btn]),
        selected_label,
        ft.Divider(),
        pages_field,
        searchable_cb,
        tcy_cb,
        advanced,
        ft.Row([run_btn]),
        progress_bar,
        status_text,
        ft.Row([open_folder_btn]),
    )


def main() -> None:
    _relocate_guard()

    if "--cli" in sys.argv:
        sys.exit(main_cli())

    import _deps  # noqa: F401 - ensures engine deps are bundled by PyInstaller
    import flet as ft

    ft.app(target=main_gui)


if __name__ == "__main__":
    main()
