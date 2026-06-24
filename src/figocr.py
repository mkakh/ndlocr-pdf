"""Figure-region OCR (§4.5 of SPEC.md).

Upstream recognizes only ``LINE`` elements, so text *inside* figure blocks
(``block_fig`` / ``block_chart`` / ``block_table`` — ``config/ndl.yaml`` class
indices 6 / 11 / 15) never gets a text layer. We re-OCR each figure region by
cropping it out of the page image and feeding the crop back through the upstream
detector + recognizer (the engine's own image path), then offset the recognized
lines back to full-page coordinates and append them to the page result.

Upstream files are NOT modified; we only import and call module-level functions
(``ocr.get_detector`` / ``ocr._run_ocr_on_image_array``) — see §4.3 補足.
"""

from __future__ import annotations

# config/ndl.yaml figure-like block classes (§4.5; §10 #2 may widen this).
FIGURE_CLASS_INDICES: tuple[int, ...] = (6, 11, 15)  # block_fig / block_chart / block_table


def _overlaps(box, other, frac: float = 0.5) -> bool:
    """True if ``box`` overlaps ``other`` by at least ``frac`` of ``box``'s area.

    Both are ``(x, y, w, h)``. Used to skip figure text that the base pipeline
    already recognized (avoids duplicating it in the output).
    """
    ax, ay, aw, ah = box
    bx, by, bw, bh = other
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    area = max(aw * ah, 1)
    return inter / area >= frac


def _figure_boxes(detections, img_w: int, img_h: int, class_indices) -> list[tuple[int, int, int, int]]:
    boxes: list[tuple[int, int, int, int]] = []
    for det in detections:
        if int(det.get("class_index", -1)) not in class_indices:
            continue
        xmin, ymin, xmax, ymax = det["box"]
        xmin = max(0, int(xmin))
        ymin = max(0, int(ymin))
        xmax = min(img_w, int(xmax))
        ymax = min(img_h, int(ymax))
        if xmax - xmin > 1 and ymax - ymin > 1:
            boxes.append((xmin, ymin, xmax, ymax))
    return boxes


def augment_page(
    ocr_module,
    detector,
    recognizer30,
    recognizer50,
    recognizer100,
    img,
    page_result: dict,
    output_dir: str,
    *,
    class_indices: tuple[int, ...] = FIGURE_CLASS_INDICES,
) -> int:
    """Re-OCR figure regions in ``img`` and append the results to ``page_result``.

    Mutates ``page_result`` in place:
      * ``text_layer_lines`` — drives the transparent PDF text layer.
      * ``text``             — drives the ``.txt`` output.
      * ``json_lines``       — drives the ``.json`` output.

    Coordinates in the appended lines are in full-page pixel space (the crop
    origin is added back), so they line up with the page's ``img_width`` /
    ``img_height`` when :func:`ocr.embed_text_layer_pdf` scales them.

    Returns the number of figure regions that yielded at least one text line.
    """
    import numpy as np

    img_h, img_w = img.shape[:2]
    boxes = _figure_boxes(detector.detect(img), img_w, img_h, class_indices)
    if not boxes:
        return 0

    # Boxes of text the base pipeline already recognized. Figure OCR must only
    # ADD text the base missed — never duplicate lines base already captured.
    covered: list[tuple[int, int, int, int]] = [
        (ln["x"], ln["y"], ln["width"], ln["height"])
        for ln in page_result.get("text_layer_lines", [])
    ]

    extra_lines: list[dict] = []
    regions_with_text = 0

    for (xmin, ymin, xmax, ymax) in boxes:
        crop = img[ymin:ymax, xmin:xmax, :]
        if crop.size == 0:
            continue
        crop_result = ocr_module._run_ocr_on_image_array(
            detector=detector,
            recognizer30=recognizer30,
            recognizer50=recognizer50,
            recognizer100=recognizer100,
            inputname="figure_crop.png",
            img=np.ascontiguousarray(crop),
            outputpath=output_dir,
            save_viz=False,
        )
        got = False
        for line in crop_result.get("text_layer_lines", []):
            text = line.get("text", "")
            if not text:
                continue
            box = (line["x"] + xmin, line["y"] + ymin, line["width"], line["height"])
            if any(_overlaps(box, c) for c in covered):
                continue  # base already read this line; don't duplicate
            got = True
            covered.append(box)  # also de-dup against other figure regions
            extra_lines.append({
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": text,
                "is_vertical": line["is_vertical"],
            })
        if got:
            regions_with_text += 1

    if not extra_lines:
        return 0

    page_result.setdefault("text_layer_lines", []).extend(extra_lines)

    joined = "\n".join(ln["text"] for ln in extra_lines)
    page_result["text"] = (page_result.get("text", "") + "\n" + joined) if page_result.get("text") else joined

    json_lines = page_result.setdefault("json_lines", [])
    base_id = len(json_lines)
    for k, ln in enumerate(extra_lines):
        x, y, w, h = ln["x"], ln["y"], ln["width"], ln["height"]
        json_lines.append({
            "boundingBox": [[x, y], [x, y + h], [x + w, y], [x + w, y + h]],
            "id": base_id + k,
            "isVertical": "true" if ln["is_vertical"] else "false",
            "text": ln["text"],
            "isTextline": "true",
            "confidence": 0.0,
            "class_index": 6,
        })

    return regions_with_text
