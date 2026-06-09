import time

import cv2
import numpy as np

from opcv2 import TEMPLATES, TEMPLATES_DIR, annotate_frame, detect_signs

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None


CAMERA_SIZE = (640, 480)
MIN_CONTOUR_AREA = 900
MIN_RADIUS = 18


def clean_mask(mask: np.ndarray) -> np.ndarray:
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return mask


def build_sign_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    red_low = cv2.inRange(hsv, (0, 120, 55), (12, 255, 255))
    red_high = cv2.inRange(hsv, (168, 120, 55), (180, 255, 255))
    red = cv2.bitwise_or(red_low, red_high)
    blue = cv2.inRange(hsv, (92, 100, 55), (132, 255, 255))

    return clean_mask(cv2.bitwise_or(red, blue))


def is_round_or_hex(contour) -> bool:
    area = cv2.contourArea(contour)
    if area < MIN_CONTOUR_AREA:
        return False

    perimeter = cv2.arcLength(contour, True)
    if perimeter <= 0:
        return False

    (_, _), radius = cv2.minEnclosingCircle(contour)
    if radius < MIN_RADIUS:
        return False

    x, y, width, height = cv2.boundingRect(contour)
    aspect_ratio = width / max(height, 1)
    if not 0.65 <= aspect_ratio <= 1.35:
        return False

    extent = area / float(max(width * height, 1))
    if not 0.45 <= extent <= 0.88:
        return False

    circularity = (4.0 * np.pi * area) / (perimeter * perimeter)
    if circularity < 0.50:
        return False

    approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
    vertices = len(approx)

    # Hexagonal signs usually give 5-7 vertices after approximation.
    # Round signs give many vertices and high circularity.
    return 5 <= vertices <= 7 or vertices >= 9


def find_sign_contours(mask: np.ndarray) -> list:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [contour for contour in contours if is_round_or_hex(contour)]


def draw_contours_on_mask(mask: np.ndarray, sign_contours: list | None = None) -> np.ndarray:
    result = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    sign_contours = find_sign_contours(mask) if sign_contours is None else sign_contours

    for contour in sign_contours:
        cv2.drawContours(result, [contour], -1, (0, 255, 0), 2)

    return result


class Camera:
    def __init__(self):
        self.picam = None
        self.cv_cam = None

    def start(self):
        if Picamera2 is not None:
            self.picam = Picamera2()
            config = self.picam.create_video_configuration(
                main={"format": "RGB888", "size": CAMERA_SIZE}
            )
            self.picam.configure(config)
            self.picam.start()
            time.sleep(0.3)
            print("Camera: Picamera2", flush=True)
            return

        self.cv_cam = cv2.VideoCapture(0)
        if not self.cv_cam.isOpened():
            raise RuntimeError("Camera was not opened")

        self.cv_cam.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_SIZE[0])
        self.cv_cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_SIZE[1])
        print("Camera: OpenCV index 0", flush=True)

    def read(self):
        if self.picam is not None:
            frame = self.picam.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        else:
            ok, frame = self.cv_cam.read()
            if not ok:
                return None

        return cv2.rotate(frame, cv2.ROTATE_180)

    def stop(self):
        if self.picam is not None:
            self.picam.stop()
            self.picam = None

        if self.cv_cam is not None:
            self.cv_cam.release()
            self.cv_cam = None


def print_current_sign(
    detections: list[dict],
    contour_count: int,
    last_label: str | None,
) -> str | None:
    if not detections:
        label = "contour/no-template" if contour_count else "none"
        if label != last_label:
            print(f"Sign: {label}", flush=True)
        return label

    best = max(detections, key=lambda item: item["score"])
    label = str(best["label"])

    if label != last_label:
        print(f"Sign: {label} ({best['score']:.2f})", flush=True)

    return label


def main():
    print(f"Templates dir: {TEMPLATES_DIR}", flush=True)
    print(f"Templates loaded: {len(TEMPLATES)}", flush=True)
    print("Press q to exit.", flush=True)

    camera = Camera()
    last_label = None

    try:
        camera.start()

        while True:
            frame = camera.read()
            if frame is None:
                print("Frame was not read", flush=True)
                time.sleep(0.1)
                continue

            mask = build_sign_mask(frame)
            sign_contours = find_sign_contours(mask)
            detections = detect_signs(frame)
            last_label = print_current_sign(detections, len(sign_contours), last_label)

            mask_view = draw_contours_on_mask(mask, sign_contours)
            camera_view = annotate_frame(frame, detections)

            cv2.imshow("Camera signs", camera_view)
            cv2.imshow("Red/blue contour mask", mask_view)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
