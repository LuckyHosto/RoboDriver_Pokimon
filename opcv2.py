from pathlib import Path

import cv2
import numpy as np


BASE_DIR = Path(__file__).resolve().parent
FACE_CASCADE_PATH = BASE_DIR / "faces.xml"

TEMPLATE_SIZE = 120
MATCH_THRESHOLD = 0.72
SECOND_BEST_MARGIN = 0.06
MIN_SIGN_AREA = 1200
MIN_RADIUS = 20
MIN_WHITE_RATIO = 0.025
MIN_COLOR_FILL_RATIO = 0.24
FINE_VERTEX_EPSILON = 0.01
COARSE_VERTEX_EPSILON = 0.03
FLIP_FRAME = True

LABELS = {
    "brick": "brick",
    "forward": "forward",
    "left": "left",
    "right": "right",
    "stop": "STOP",
}

_camera = None
_last_announced_labels = set()


def _find_templates_dir() -> Path | None:
    preferred_names = ("SET_ZNAKC", "Set_znakc", "set_znakc")
    for name in preferred_names:
        path = BASE_DIR / name
        if path.exists() and path.is_dir():
            return path

    for path in BASE_DIR.iterdir():
        if path.is_dir() and path.name.lower() == "set_znakc":
            return path

    return None


TEMPLATES_DIR = _find_templates_dir()


def _clean_mask(mask: np.ndarray, kernel_size: int = 5) -> np.ndarray:
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return mask


def _build_color_masks(hsv: np.ndarray) -> dict[str, np.ndarray]:
    blue = cv2.inRange(hsv, (92, 100, 55), (132, 255, 255))
    red_low = cv2.inRange(hsv, (0, 120, 55), (12, 255, 255))
    red_high = cv2.inRange(hsv, (168, 120, 55), (180, 255, 255))
    red = cv2.bitwise_or(red_low, red_high)
    white = cv2.inRange(hsv, (0, 0, 170), (180, 70, 255))
    return {
        "blue": _clean_mask(blue),
        "red": _clean_mask(red),
        "white": _clean_mask(white, kernel_size=3),
    }


def _largest_contour(mask: np.ndarray):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _dominant_color(masks: dict[str, np.ndarray]) -> str | None:
    red_pixels = cv2.countNonZero(masks["red"])
    blue_pixels = cv2.countNonZero(masks["blue"])
    if red_pixels == 0 and blue_pixels == 0:
        return None
    return "red" if red_pixels > blue_pixels else "blue"


def _crop_square(image: np.ndarray, contour) -> np.ndarray:
    height, width = image.shape[:2]
    (cx, cy), radius = cv2.minEnclosingCircle(contour)
    radius = max(radius * 1.2, 24)
    x1 = max(int(cx - radius), 0)
    y1 = max(int(cy - radius), 0)
    x2 = min(int(cx + radius), width)
    y2 = min(int(cy + radius), height)
    return image[y1:y2, x1:x2]


def _score_delta(a: float, b: float, scale: float) -> float:
    if scale <= 0:
        return 1.0 if a == b else 0.0
    return max(0.0, 1.0 - (abs(a - b) / scale))


def _red_shape_hint(color: str, fine_vertices: int) -> str | None:
    if color != "red":
        return None
    if fine_vertices <= 10:
        return "octagon"
    if fine_vertices >= 12:
        return "round"
    return None


def _shape_hint_score(candidate: dict, template: dict) -> float:
    candidate_hint = candidate.get("shape_hint")
    template_hint = template.get("shape_hint")
    if candidate_hint is None or template_hint is None:
        return 0.5
    return 1.0 if candidate_hint == template_hint else 0.0


def _extract_features(image: np.ndarray, forced_color: str | None = None) -> dict | None:
    if image is None or image.size == 0:
        return None

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masks = _build_color_masks(hsv)
    color = forced_color or _dominant_color(masks)
    if color is None:
        return None

    contour = _largest_contour(masks[color])
    if contour is None or cv2.contourArea(contour) < MIN_SIGN_AREA:
        return None

    cropped = _crop_square(image, contour)
    if cropped.size == 0:
        return None

    normalized = cv2.resize(cropped, (TEMPLATE_SIZE, TEMPLATE_SIZE), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(normalized, cv2.COLOR_BGR2HSV)
    masks = _build_color_masks(hsv)
    color_mask = masks[color]
    main_contour = _largest_contour(color_mask)
    if main_contour is None:
        return None

    sign_region = np.zeros_like(color_mask)
    cv2.drawContours(sign_region, [main_contour], -1, 255, thickness=cv2.FILLED)

    white_mask = cv2.bitwise_and(masks["white"], sign_region)
    white_mask = _clean_mask(white_mask, kernel_size=3)

    gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    gray = cv2.bitwise_and(gray, gray, mask=sign_region)
    edges = cv2.Canny(gray, 60, 150)

    contour_area = cv2.contourArea(main_contour)
    contour_perimeter = cv2.arcLength(main_contour, True)
    if contour_area <= 0 or contour_perimeter <= 0:
        return None

    circularity = (4.0 * np.pi * contour_area) / (contour_perimeter * contour_perimeter)
    fine_vertices = len(cv2.approxPolyDP(main_contour, FINE_VERTEX_EPSILON * contour_perimeter, True))
    coarse_vertices = len(cv2.approxPolyDP(main_contour, COARSE_VERTEX_EPSILON * contour_perimeter, True))

    fill_ratio = cv2.countNonZero(sign_region) / float(TEMPLATE_SIZE * TEMPLATE_SIZE)
    white_ratio = cv2.countNonZero(white_mask) / max(cv2.countNonZero(sign_region), 1)

    return {
        "color": color,
        "normalized": normalized,
        "gray": gray,
        "edges": edges,
        "sign_region": sign_region,
        "symbol": white_mask,
        "fill_ratio": fill_ratio,
        "white_ratio": white_ratio,
        "circularity": circularity,
        "fine_vertices": fine_vertices,
        "coarse_vertices": coarse_vertices,
        "shape_hint": _red_shape_hint(color, fine_vertices),
    }


def _norm_corr(a: np.ndarray, b: np.ndarray) -> float:
    score = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0][0])
    return (score + 1.0) / 2.0


def _compare_features(candidate: dict, template: dict) -> float:
    symbol_corr = _norm_corr(candidate["symbol"], template["symbol"])
    symbol_diff = 1.0 - (np.mean(cv2.absdiff(candidate["symbol"], template["symbol"])) / 255.0)
    gray_corr = _norm_corr(candidate["gray"], template["gray"])
    edge_diff = 1.0 - (np.mean(cv2.absdiff(candidate["edges"], template["edges"])) / 255.0)
    shape_corr = _norm_corr(candidate["sign_region"], template["sign_region"])
    shape_diff = 1.0 - (np.mean(cv2.absdiff(candidate["sign_region"], template["sign_region"])) / 255.0)
    fill_score = _score_delta(candidate["fill_ratio"], template["fill_ratio"], 0.35)
    white_score = _score_delta(candidate["white_ratio"], template["white_ratio"], 0.25)
    circularity_score = _score_delta(candidate["circularity"], template["circularity"], 0.10)
    fine_vertex_score = _score_delta(candidate["fine_vertices"], template["fine_vertices"], 10.0)
    coarse_vertex_score = _score_delta(candidate["coarse_vertices"], template["coarse_vertices"], 4.0)

    score = (
        0.24 * symbol_corr
        + 0.14 * symbol_diff
        + 0.12 * gray_corr
        + 0.06 * edge_diff
        + 0.16 * shape_corr
        + 0.08 * shape_diff
        + 0.08 * fine_vertex_score
        + 0.04 * coarse_vertex_score
        + 0.03 * circularity_score
        + 0.03 * fill_score
        + 0.02 * white_score
    )

    if candidate["color"] == "red" and template["color"] == "red":
        score *= 0.75 + 0.25 * _shape_hint_score(candidate, template)

    return score


def _load_templates() -> list[dict]:
    templates = []
    if TEMPLATES_DIR is None or not TEMPLATES_DIR.exists():
        return templates

    for path in sorted(TEMPLATES_DIR.rglob("*")):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue

        image = cv2.imread(str(path))
        features = _extract_features(image)
        if features is None:
            continue

        templates.append(
            {
                "name": path.name,
                "label": LABELS.get(path.stem.lower(), path.stem),
                "features": features,
            }
        )

    return templates


def _load_face_cascade():
    if not FACE_CASCADE_PATH.exists():
        return None

    cascade = cv2.CascadeClassifier(str(FACE_CASCADE_PATH))
    return None if cascade.empty() else cascade


TEMPLATES = _load_templates()
FACE_CASCADE = _load_face_cascade()


def _announce_detections(detections: list[dict]) -> None:
    global _last_announced_labels

    current_labels = {detection["label"] for detection in detections}
    new_labels = sorted(current_labels - _last_announced_labels)

    for label in new_labels:
        print(f"Detected sign: {label}", flush=True)

    _last_announced_labels = current_labels


def _boxes_overlap(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int], threshold: float = 0.25) -> bool:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return False

    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    min_area = min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1))
    return (inter_area / max(min_area, 1)) >= threshold


def _detect_faces(gray_frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    if FACE_CASCADE is None:
        return []

    faces = FACE_CASCADE.detectMultiScale(
        gray_frame,
        scaleFactor=1.15,
        minNeighbors=5,
        minSize=(48, 48),
    )
    return [(x, y, x + w, y + h) for x, y, w, h in faces]


def _candidate_boxes(frame: np.ndarray, faces: list[tuple[int, int, int, int]]) -> list[dict]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    masks = _build_color_masks(hsv)
    height, width = frame.shape[:2]
    candidates = []

    for color in ("red", "blue"):
        contours, _ = cv2.findContours(masks[color], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < MIN_SIGN_AREA:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue

            circularity = (4.0 * np.pi * area) / (perimeter * perimeter)
            min_circularity = 0.38 if color == "red" else 0.48
            if circularity < min_circularity:
                continue

            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            if radius < MIN_RADIUS:
                continue

            pad = int(radius * 1.2)
            x1 = max(int(cx - pad), 0)
            y1 = max(int(cy - pad), 0)
            x2 = min(int(cx + pad), width)
            y2 = min(int(cy + pad), height)
            if x2 <= x1 or y2 <= y1:
                continue

            box_width = x2 - x1
            box_height = y2 - y1
            aspect_ratio = box_width / max(box_height, 1)
            if not 0.70 <= aspect_ratio <= 1.30:
                continue

            box = (x1, y1, x2, y2)
            if any(_boxes_overlap(box, face_box) for face_box in faces):
                continue

            bbox_area = box_width * box_height
            color_pixels = cv2.countNonZero(masks[color][y1:y2, x1:x2])
            color_fill = color_pixels / max(bbox_area, 1)
            if color_fill < MIN_COLOR_FILL_RATIO:
                continue

            roi = frame[y1:y2, x1:x2]
            features = _extract_features(roi, forced_color=color)
            if features is None:
                continue

            if features["white_ratio"] < MIN_WHITE_RATIO:
                continue

            candidates.append(
                {
                    "box": box,
                    "features": features,
                    "area": area,
                    "color_fill": color_fill,
                    "circularity": circularity,
                }
            )

    return candidates


def detect_signs(frame: np.ndarray) -> list[dict]:
    if frame is None or frame.size == 0 or not TEMPLATES:
        return []

    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray_frame)
    detections = []

    for candidate in _candidate_boxes(frame, faces):
        best_template = None
        best_score = 0.0
        second_score = 0.0

        for template in TEMPLATES:
            if template["features"]["color"] != candidate["features"]["color"]:
                continue

            score = _compare_features(candidate["features"], template["features"])
            if score > best_score:
                second_score = best_score
                best_score = score
                best_template = template
            elif score > second_score:
                second_score = score

        if best_template is None or best_score < MATCH_THRESHOLD:
            continue
        if second_score > 0.0 and best_score - second_score < SECOND_BEST_MARGIN:
            continue

        detections.append(
            {
                "label": best_template["label"],
                "name": best_template["name"],
                "score": best_score,
                "second_score": second_score,
                "box": candidate["box"],
            }
        )

    detections.sort(key=lambda item: item["score"], reverse=True)

    filtered = []
    for detection in detections:
        if any(_boxes_overlap(detection["box"], kept["box"], threshold=0.35) for kept in filtered):
            continue
        filtered.append(detection)

    return filtered


def annotate_frame(frame: np.ndarray, detections: list[dict] | None = None) -> np.ndarray:
    result = frame.copy()
    detections = detect_signs(frame) if detections is None else detections

    for detection in detections:
        x1, y1, x2, y2 = detection["box"]
        cv2.rectangle(result, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{detection['label']} {detection['score']:.2f}"
        text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        text_x = x1
        text_y = max(text_size[1] + 8, y1 - 8)
        cv2.rectangle(
            result,
            (text_x, text_y - text_size[1] - 6),
            (text_x + text_size[0] + 8, text_y + 4),
            (0, 120, 0),
            cv2.FILLED,
        )
        cv2.putText(
            result,
            label,
            (text_x + 4, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

    if not TEMPLATES:
        cv2.putText(
            result,
            "Templates not found",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 0, 255),
            2,
        )

    return result


def orient_frame(frame: np.ndarray) -> np.ndarray:
    if FLIP_FRAME:
        return cv2.rotate(frame, cv2.ROTATE_180)
    return frame


def _open_camera():
    global _camera

    if _camera is None:
        _camera = cv2.VideoCapture(0)
        if not _camera.isOpened():
            _camera.release()
            _camera = None

    return _camera


def get_frame():
    camera = _open_camera()
    if camera is None:
        return None

    ok, frame = camera.read()
    if not ok:
        return None

    frame = orient_frame(frame)
    detections = detect_signs(frame)
    _announce_detections(detections)
    return annotate_frame(frame, detections)


def release():
    global _camera, _last_announced_labels

    if _camera is not None:
        _camera.release()
        _camera = None

    _last_announced_labels = set()

    cv2.destroyAllWindows()


def main():
    while True:
        frame = get_frame()
        if frame is None:
            break

        cv2.imshow("Road Sign Detection", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    release()


if __name__ == "__main__":
    main()
