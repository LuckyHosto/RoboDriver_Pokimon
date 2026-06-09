import argparse
import time
from collections import deque

import cv2
import serial
import serial.tools.list_ports

from opcv2 import annotate_frame, detect_signs, orient_frame, release as release_opencv

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None


DEFAULT_PORTS = ("/dev/ttyUSB0", "/dev/ttyACM0", "COM3", "COM4")
DEFAULT_BAUDRATE = 9600
DEFAULT_SPEED = 155
CAMERA_SIZE = (640, 480)
MIN_COMMAND_INTERVAL = 1.0
STABLE_FRAMES = 3

SIGN_COMMANDS = {
    "brick": "BRICK",
    "forward": "FORWARD",
    "left": "LEFT",
    "right": "RIGHT",
    "tight": "RIGHT",
    "stop": "STOP",
}


class Camera:
    def __init__(self, index: int = 0):
        self._picam = None
        self._cv_cam = None
        self._index = index

    def start(self):
        if Picamera2 is not None:
            self._picam = Picamera2()
            config = self._picam.create_video_configuration(
                main={"format": "RGB888", "size": CAMERA_SIZE}
            )
            self._picam.configure(config)
            self._picam.start()
            time.sleep(0.3)
            print("Camera: Picamera2", flush=True)
            return

        self._cv_cam = cv2.VideoCapture(self._index)
        if not self._cv_cam.isOpened():
            raise RuntimeError("Camera was not opened")

        self._cv_cam.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_SIZE[0])
        self._cv_cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_SIZE[1])
        print(f"Camera: OpenCV index {self._index}", flush=True)

    def read(self):
        if self._picam is not None:
            frame = self._picam.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return orient_frame(frame)

        ok, frame = self._cv_cam.read()
        return orient_frame(frame) if ok else None

    def stop(self):
        if self._picam is not None:
            self._picam.stop()
            self._picam = None

        if self._cv_cam is not None:
            self._cv_cam.release()
            self._cv_cam = None


def list_serial_ports() -> list[str]:
    return [port.device for port in serial.tools.list_ports.comports()]


def open_serial(port: str | None, baudrate: int) -> serial.Serial:
    candidates = [port] if port else [*DEFAULT_PORTS, *list_serial_ports()]
    seen = set()

    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)

        try:
            ser = serial.Serial(candidate, baudrate, timeout=0.05)
            time.sleep(2.0)
            print(f"Serial: connected to {candidate}", flush=True)
            return ser
        except serial.SerialException:
            pass

    raise RuntimeError("Arduino serial port was not found")


def send_command(ser: serial.Serial, command: str) -> None:
    ser.write((command + "\n").encode("utf-8"))
    ser.flush()
    print(f"> {command}", flush=True)


def normalize_label(label: str) -> str:
    return label.strip().lower()


def choose_label(detections: list[dict]) -> str | None:
    if not detections:
        return None

    best = max(detections, key=lambda item: item["score"])
    return normalize_label(best["label"])


def stable_label(history: deque[str | None]) -> str | None:
    labels = [label for label in history if label is not None]
    if len(labels) < STABLE_FRAMES:
        return None

    latest = labels[-1]
    if labels[-STABLE_FRAMES:].count(latest) == STABLE_FRAMES:
        return latest

    return None


def run(args: argparse.Namespace) -> None:
    ser = None if args.camera_only else open_serial(args.port, args.baudrate)
    camera = Camera(args.camera_index)
    history: deque[str | None] = deque(maxlen=STABLE_FRAMES)
    last_command = None
    last_sent_at = 0.0

    try:
        camera.start()
        if ser is not None:
            send_command(ser, f"SPEED {args.speed}")
            send_command(ser, "READY")

        while True:
            frame = camera.read()
            if frame is None:
                print("Camera frame was not read", flush=True)
                time.sleep(0.1)
                continue

            detections = detect_signs(frame)
            label = choose_label(detections)
            history.append(label)
            stable = stable_label(history)

            if ser is not None and stable in SIGN_COMMANDS:
                command = SIGN_COMMANDS[stable]
                now = time.monotonic()
                can_repeat = command in {"LEFT", "RIGHT", "BRICK"}

                if (
                    command != last_command or can_repeat
                ) and now - last_sent_at >= MIN_COMMAND_INTERVAL:
                    send_command(ser, command)
                    last_command = command
                    last_sent_at = now
                    history.clear()

            if not args.no_show:
                cv2.imshow("RoboDriver signs", annotate_frame(frame, detections))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if ser is not None:
                while ser.in_waiting:
                    print("< " + ser.readline().decode("utf-8", errors="replace").strip(), flush=True)

    finally:
        if ser is not None:
            send_command(ser, "STOP")
            ser.close()
        camera.stop()
        release_opencv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Raspberry Pi logic for RoboDriver.")
    parser.add_argument("--port", default=None, help="Arduino serial port, for example /dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--speed", type=int, default=DEFAULT_SPEED)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--camera-only", action="store_true", help="Show recognition without Arduino commands")
    parser.add_argument("--no-show", action="store_true", help="Do not show OpenCV debug window")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
