"""Force-import the upstream engine's third-party dependencies.

The OCR engine is loaded dynamically at runtime (its directory is inserted into
``sys.path`` and ``import ocr`` follows), so PyInstaller's static analysis never
sees these packages. Importing them here with **static import statements** — and
importing this module from ``app.py`` — makes PyInstaller bundle them. The §7.2
build-smoke test is the backstop that proves nothing is missing.

These MUST be real ``import`` statements (not ``importlib.import_module``):
PyInstaller's static analyser does not follow string-based dynamic imports.

(``pandas`` is intentionally excluded: it is only used by the table-recognition
path which the PDF-OCR pipeline never touches and which is not in requirements.)
"""

# ruff: noqa: F401  (these imports exist purely to be discovered by PyInstaller)

import cv2
import lxml
import lxml.etree
import networkx
import numpy
import onnxruntime
import PIL
import PIL.Image
import pypdf
import pypdfium2
import reportlab
import reportlab.pdfbase.cidfonts
import reportlab.pdfgen.canvas
import tqdm
import yaml
