"""Page-spec parser (§5.2 of SPEC.md).

Parses a user page expression such as ``"1,3,5-8"`` into a sorted, de-duplicated
list of 1-based page numbers. An empty / whitespace-only spec means "all pages"
and is represented by the sentinel ``None`` (NOT an empty list) so that the
caller can skip page extraction and feed the original PDF unchanged.
"""

from __future__ import annotations


class PageSpecError(ValueError):
    """Raised when a page expression is invalid or yields no pages.

    Carries a Japanese, end-user-facing message suitable for showing in the GUI.
    """


def parse_pages(spec: str, total: int) -> list[int] | None:
    """Parse a page expression against a document of ``total`` pages.

    Args:
        spec: expression like ``"1,3,5-8"``. Whitespace is ignored. Empty or
            whitespace-only means "all pages".
        total: total number of pages in the document (used for range checks).
            Must be >= 1.

    Returns:
        ``None`` for "all pages", otherwise a sorted, de-duplicated list of
        1-based page numbers.

    Raises:
        PageSpecError: on non-numeric tokens, reversed ranges (e.g. ``5-2``),
            out-of-range pages (e.g. ``0`` or ``999``), malformed syntax, or an
            empty result.
    """
    if total < 1:
        raise PageSpecError("PDF にページがありません。")

    if spec is None or spec.strip() == "":
        return None

    # Remove all whitespace anywhere in the expression.
    compact = "".join(spec.split())

    pages: set[int] = set()
    for token in compact.split(","):
        if token == "":
            # Handles empty tokens from leading/trailing/double commas: "1,",",2", "1,,2".
            raise PageSpecError(
                f"ページ指定の書式が正しくありません: '{spec}'（空の項目があります）。"
            )

        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2 or parts[0] == "" or parts[1] == "":
                raise PageSpecError(
                    f"ページ範囲の書式が正しくありません: '{token}'（例: 5-8）。"
                )
            start = _parse_int(parts[0], spec)
            end = _parse_int(parts[1], spec)
            if start > end:
                raise PageSpecError(
                    f"ページ範囲が逆順です: '{token}'（小さい番号を先に指定してください）。"
                )
            _check_range(start, total, spec)
            _check_range(end, total, spec)
            pages.update(range(start, end + 1))
        else:
            value = _parse_int(token, spec)
            _check_range(value, total, spec)
            pages.add(value)

    if not pages:
        raise PageSpecError(f"有効なページが指定されていません: '{spec}'。")

    return sorted(pages)


def _parse_int(token: str, spec: str) -> int:
    try:
        return int(token)
    except ValueError:
        raise PageSpecError(
            f"ページ指定に数字以外が含まれています: '{token}'（指定: '{spec}'）。"
        ) from None


def _check_range(value: int, total: int, spec: str) -> None:
    if value < 1:
        raise PageSpecError(
            f"ページ番号は 1 以上で指定してください: '{value}'（指定: '{spec}'）。"
        )
    if value > total:
        raise PageSpecError(
            f"ページ番号 {value} は総ページ数 {total} を超えています（指定: '{spec}'）。"
        )
