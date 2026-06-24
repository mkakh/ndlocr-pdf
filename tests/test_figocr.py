"""Unit tests for figocr.augment_page (§4.5) — logic only, no models.

A fake upstream ``ocr`` module and detector feed controlled detections /
recognition results so we can assert the offset math, the base-text de-dup
(figure OCR must not duplicate text the base pipeline already read), and the
mutation of ``page_result`` (text_layer_lines / text / json_lines).
"""

import numpy as np

import figocr


class FakeDetector:
    def __init__(self, detections):
        self._detections = detections

    def detect(self, img):
        return self._detections


class FakeOcr:
    """Stand-in for the upstream ``ocr`` module."""

    def __init__(self, crop_lines):
        self._crop_lines = crop_lines

    def _run_ocr_on_image_array(self, *, detector, recognizer30, recognizer50,
                                recognizer100, inputname, img, outputpath, save_viz=False):
        # Returns the same crop result regardless of which crop (good enough for
        # a single-figure test).
        return {"text_layer_lines": list(self._crop_lines)}


def _img(h=800, w=1000):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _fig_det(box, class_index=6):
    return {"class_index": class_index, "confidence": 0.9, "box": box, "pred_char_count": 100.0}


def _empty_page_result():
    return {"text_layer_lines": [], "text": "本文", "json_lines": [
        {"boundingBox": [[0, 0], [0, 10], [10, 0], [10, 10]], "id": 0, "isVertical": "false",
         "text": "本文", "isTextline": "true", "confidence": 0.9, "class_index": 1},
    ]}


def test_appends_offset_figure_line():
    page_result = _empty_page_result()
    detector = FakeDetector([_fig_det([100, 200, 400, 360])])
    crop_lines = [{"x": 10, "y": 20, "width": 80, "height": 24, "text": "図中認識試験", "is_vertical": False}]
    ocr = FakeOcr(crop_lines)

    n = figocr.augment_page(ocr, detector, None, None, None, _img(), page_result, "out")

    assert n == 1
    # offset by the figure box origin (100, 200)
    added = page_result["text_layer_lines"][-1]
    assert (added["x"], added["y"]) == (110, 220)
    assert added["text"] == "図中認識試験"
    # text + json updated
    assert "図中認識試験" in page_result["text"]
    assert page_result["text"].startswith("本文")
    assert page_result["json_lines"][-1]["text"] == "図中認識試験"


def test_dedups_against_base_line():
    # Base already has a line where the figure crop line would land -> skip it.
    page_result = _empty_page_result()
    page_result["text_layer_lines"].append(
        {"x": 110, "y": 220, "width": 80, "height": 24, "text": "図中認識試験", "is_vertical": False}
    )
    detector = FakeDetector([_fig_det([100, 200, 400, 360])])
    crop_lines = [{"x": 10, "y": 20, "width": 80, "height": 24, "text": "図中認識試験", "is_vertical": False}]
    ocr = FakeOcr(crop_lines)

    n = figocr.augment_page(ocr, detector, None, None, None, _img(), page_result, "out")

    assert n == 0
    # nothing appended beyond the pre-existing base line
    assert len(page_result["text_layer_lines"]) == 1
    assert page_result["text"] == "本文"


def test_no_figure_classes_is_noop():
    page_result = _empty_page_result()
    before = dict(page_result)
    # only a text-class detection, no figure block
    detector = FakeDetector([_fig_det([100, 200, 400, 360], class_index=1)])
    ocr = FakeOcr([{"x": 1, "y": 1, "width": 10, "height": 10, "text": "x", "is_vertical": False}])

    n = figocr.augment_page(ocr, detector, None, None, None, _img(), page_result, "out")

    assert n == 0
    assert page_result["text"] == before["text"]
    assert page_result["text_layer_lines"] == []


def test_skips_empty_text_lines():
    page_result = _empty_page_result()
    detector = FakeDetector([_fig_det([100, 200, 400, 360])])
    ocr = FakeOcr([{"x": 10, "y": 20, "width": 80, "height": 24, "text": "", "is_vertical": False}])

    n = figocr.augment_page(ocr, detector, None, None, None, _img(), page_result, "out")

    assert n == 0
    assert page_result["text_layer_lines"] == []


def test_overlaps_helper():
    assert figocr._overlaps((0, 0, 100, 100), (0, 0, 100, 100))
    assert figocr._overlaps((0, 0, 100, 100), (50, 0, 100, 100))  # 50% overlap
    assert not figocr._overlaps((0, 0, 100, 100), (90, 0, 100, 100))  # 10% overlap
    assert not figocr._overlaps((0, 0, 100, 100), (200, 200, 50, 50))  # disjoint
