"""Generate the distributable NOTICE file (§8 of SPEC.md).

Composition:
  1. NDL NDLOCR-Lite attribution (CC BY 4.0) + original link.
  2. Our changes (the page-selection GUI/CLI wrapper).
  3. Machine-generated third-party license inventory taken from the *installed*
     environment metadata (the resolved ``uv.lock`` is the source of truth, not a
     hand-written list), so dependency updates can't silently drift.

Run with the project venv:  uv run python tools/gen_notice.py
CI runs this before packaging and includes the produced NOTICE in the zip.
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "NOTICE"

UPSTREAM_REF = "1.2.3"

HEADER = f"""NDLOCR-PDF — NOTICE
===================

This application bundles and builds upon third-party software. Attributions and
license terms are reproduced below.

------------------------------------------------------------------------------
1. NDLOCR-Lite (OCR engine and ONNX models)
------------------------------------------------------------------------------
Copyright (c) National Diet Library, Japan.
Source: https://github.com/ndl-lab/ndlocr-lite  (pinned tag: {UPSTREAM_REF})
License: Creative Commons Attribution 4.0 International (CC BY 4.0)
         https://creativecommons.org/licenses/by/4.0/

The NDLOCR-Lite source (under external/ndlocr-lite) and its ONNX model files are
redistributed unmodified under CC BY 4.0, with attribution to the National Diet
Library.

------------------------------------------------------------------------------
2. Changes made by this project
------------------------------------------------------------------------------
This project adds a thin driver, a desktop GUI (Flet) and a headless CLI around
NDLOCR-Lite. Specifically it adds page-range selection, non-ASCII path handling,
output renaming, and Windows packaging. The upstream engine code is NOT modified
(it is consumed as a git submodule pinned to tag {UPSTREAM_REF}).

The wrapper code authored by this project (src/, tests/, tools/) is licensed
under the MIT License (see the LICENSE file). This does not affect the CC BY 4.0
terms of the bundled NDLOCR-Lite engine and models below.

------------------------------------------------------------------------------
3. Third-party Python dependencies (generated from the installed environment)
------------------------------------------------------------------------------
"""


def _license_of(dist: metadata.Distribution) -> str:
    md = dist.metadata
    # Prefer the License-Expression / License field, fall back to classifiers.
    expr = md.get("License-Expression")
    if expr:
        return expr.strip()
    lic = md.get("License")
    if lic and len(lic.strip()) < 120 and "\n" not in lic.strip():
        return lic.strip()
    classifiers = md.get_all("Classifier") or []
    licenses = [c.split("::")[-1].strip() for c in classifiers if c.startswith("License ::")]
    if licenses:
        return "; ".join(licenses)
    return "(see project metadata)"


def _collect_license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for f in dist.files or []:
        name = f.name.upper()
        if name.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
            try:
                texts.append((f.name, f.read_text()))
            except Exception:
                pass
    return texts


def main() -> int:
    dists = sorted(
        metadata.distributions(),
        key=lambda d: (d.metadata.get("Name") or "").lower(),
    )
    seen: set[str] = set()
    lines: list[str] = [HEADER]
    full_texts: list[str] = []

    for dist in dists:
        name = dist.metadata.get("Name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        version = dist.version
        lic = _license_of(dist)
        lines.append(f"- {name} {version} — {lic}")
        for fname, text in _collect_license_texts(dist):
            full_texts.append(
                f"\n\n===== {name} {version} :: {fname} =====\n{text}"
            )

    lines.append("\n")
    lines.append("=" * 78)
    lines.append("Full license texts (as shipped in each package's metadata)")
    lines.append("=" * 78)
    body = "\n".join(lines) + "".join(full_texts) + "\n"
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} ({len(seen)} packages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
