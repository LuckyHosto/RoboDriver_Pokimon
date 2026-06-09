import argparse
import html
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

try:
    import serial
    import serial.tools.list_ports
except ImportError as exc:
    raise SystemExit(
        "PySerial is not installed. Install it on Raspberry Pi with: "
        "python -m pip install pyserial"
    ) from exc


DEFAULT_PORTS = ("/dev/ttyUSB0", "/dev/ttyACM0", "COM3", "COM4")
DEFAULT_BAUDRATE = 9600
DEFAULT_WEB_PORT = 8080
DEFAULT_SPEED = 155
CAMERA_SIZE = (640, 480)
JPEG_QUALITY = 72

COMMANDS = {
    "forward": "FORWARD",
    "backward": "BACKWARD",
    "left": "TURN_LEFT",
    "right": "TURN_RIGHT",
    "stop": "STOP",
}

HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RoboDriver TEST Drive</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Arial, sans-serif;
      background: #101215;
      color: #f4f7fb;
    }
    body {
      margin: 0;
      min-height: 100svh;
      display: flex;
      justify-content: center;
      align-items: stretch;
      overflow-x: hidden;
    }
    main {
      width: min(96vw, 620px);
      min-height: 100svh;
      display: grid;
      grid-template-rows: auto auto;
      gap: 8px;
      padding: 8px;
      box-sizing: border-box;
    }
    .camera {
      background: #050607;
      border: 1px solid #303744;
      border-radius: 8px;
      overflow: hidden;
      display: grid;
      place-items: center;
    }
    .camera img {
      width: 100%;
      height: min(42svh, 360px);
      object-fit: contain;
      display: block;
    }
    .panel {
      background: #1b2028;
      border: 1px solid #303744;
      border-radius: 8px;
      padding: 10px;
      display: grid;
      gap: 10px;
    }
    .pad {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      grid-template-rows: repeat(3, clamp(62px, 12svh, 90px));
      gap: 8px;
    }
    button {
      border: 0;
      border-radius: 8px;
      background: #2e3745;
      color: #fff;
      font-size: clamp(16px, 4.4vw, 22px);
      font-weight: 700;
      touch-action: none;
      user-select: none;
      cursor: pointer;
    }
    button:active,
    button.active {
      background: #f1b51c;
      color: #111;
    }
    .forward { grid-column: 2; grid-row: 1; }
    .left { grid-column: 1; grid-row: 2; }
    .stop { grid-column: 2; grid-row: 2; background: #b82d2d; }
    .right { grid-column: 3; grid-row: 2; }
    .backward { grid-column: 2; grid-row: 3; }
    label {
      display: grid;
      gap: 6px;
      font-size: 15px;
    }
    input[type="range"] {
      width: 100%;
    }
    .status {
      min-height: 20px;
      color: #aeb8c8;
      font-family: Consolas, monospace;
      font-size: 13px;
      word-break: break-word;
    }
  </style>
</head>
<body>
  <main>
    <section class="camera">
      <img src="/stream" alt="Camera stream">
    </section>
    <section class="panel">
      <div class="pad">
        <button class="forward" data-cmd="forward">FWD</button>
        <button class="left" data-cmd="left">LEFT</button>
        <button class="stop" data-cmd="stop">STOP</button>
        <button class="right" data-cmd="right">RIGHT</button>
        <button class="backward" data-cmd="backward">BACK</button>
      </div>
      <label>
        Speed: <span id="speedValue">155</span>
        <input id="speed" type="range" min="0" max="255" value="155">
      </label>
      <div id="status" class="status">Ready</div>
    </section>
  </main>
  <script>
    const statusEl = document.querySelector("#status");
    const speed = document.querySelector("#speed");
    const speedValue = document.querySelector("#speedValue");
    let activeButton = null;

    async function send(cmd) {
      const response = await fetch(`/api/command?cmd=${encodeURIComponent(cmd)}`);
      const data = await response.json();
      statusEl.textContent = data.ok ? `> ${data.sent}` : data.error;
    }

    async function setSpeed(value) {
      speedValue.textContent = value;
      const response = await fetch(`/api/speed?value=${encodeURIComponent(value)}`);
      const data = await response.json();
      statusEl.textContent = data.ok ? `> ${data.sent}` : data.error;
    }

    document.querySelectorAll("button[data-cmd]").forEach((button) => {
      const cmd = button.dataset.cmd;

      button.addEventListener("pointerdown", async (event) => {
        event.preventDefault();
        activeButton = button;
        button.classList.add("active");
        await send(cmd);
      });

      const release = async () => {
        if (activeButton === button && cmd !== "stop") {
          activeButton = null;
          button.classList.remove("active");
          await send("stop");
        }
      };

      button.addEventListener("pointerup", release);
      button.addEventListener("pointercancel", release);
      button.addEventListener("pointerleave", release);
    });

    speed.addEventListener("change", () => setSpeed(speed.value));
    window.addEventListener("beforeunload", () => navigator.sendBeacon("/api/command?cmd=stop"));
  </script>
</body>
</html>
"""


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
            ser = serial.Serial(candidate, baudrate, timeout=0.1)
            time.sleep(2.0)
            print(f"Serial connected: {candidate}", flush=True)
            return ser
        except serial.SerialException:
            pass

    raise RuntimeError("Arduino serial port was not found")


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class CameraStream:
    def __init__(self, camera_index: int, width: int, height: int, fps: float):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.frame_delay = 1.0 / max(fps, 1.0)
        self.picam = None
        self.cv_cam = None
        self.latest_jpeg = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)

    def start(self) -> None:
        if Picamera2 is not None:
            self.picam = Picamera2()
            config = self.picam.create_video_configuration(
                main={"format": "RGB888", "size": (self.width, self.height)}
            )
            self.picam.configure(config)
            self.picam.start()
            print("Camera connected: Picamera2", flush=True)
        else:
            self.cv_cam = cv2.VideoCapture(self.camera_index)
            if not self.cv_cam.isOpened():
                raise RuntimeError("Camera was not opened")
            self.cv_cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cv_cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            print(f"Camera connected: OpenCV index {self.camera_index}", flush=True)

        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.picam is not None:
            self.picam.stop()
            self.picam = None
        if self.cv_cam is not None:
            self.cv_cam.release()
            self.cv_cam = None

    def get_jpeg(self) -> bytes | None:
        with self.lock:
            return self.latest_jpeg

    def _read_frame(self):
        if self.picam is not None:
            return self.picam.capture_array()

        ok, frame = self.cv_cam.read()
        return frame if ok else None

    def _capture_loop(self) -> None:
        while not self.stop_event.is_set():
            frame = self._read_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            frame = cv2.rotate(frame, cv2.ROTATE_180)
            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
            )
            if ok:
                with self.lock:
                    self.latest_jpeg = encoded.tobytes()

            time.sleep(self.frame_delay)


class DriveState:
    def __init__(self, ser: serial.Serial, speed: int, camera: CameraStream):
        self.ser = ser
        self.camera = camera
        self.speed = max(0, min(255, speed))
        self.last_sent = ""

    def send(self, command: str) -> str:
        self.ser.write((command + "\n").encode("utf-8"))
        self.ser.flush()
        self.last_sent = command
        print(f"> {command}", flush=True)
        return command


def make_handler(state: DriveState):
    class DriveHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)

            if parsed.path == "/":
                self.send_html(HTML_PAGE)
                return

            if parsed.path == "/stream":
                self.send_stream()
                return

            if parsed.path == "/api/command":
                params = parse_qs(parsed.query)
                cmd = params.get("cmd", [""])[0].lower()
                if cmd not in COMMANDS:
                    self.send_json({"ok": False, "error": f"Unknown command: {html.escape(cmd)}"}, 400)
                    return

                sent = state.send(COMMANDS[cmd])
                self.send_json({"ok": True, "sent": sent})
                return

            if parsed.path == "/api/speed":
                params = parse_qs(parsed.query)
                try:
                    value = int(params.get("value", [state.speed])[0])
                except ValueError:
                    self.send_json({"ok": False, "error": "Bad speed"}, 400)
                    return

                state.speed = max(0, min(255, value))
                sent = state.send(f"SPEED {state.speed}")
                self.send_json({"ok": True, "sent": sent})
                return

            self.send_json({"ok": False, "error": "Not found"}, 404)

        def log_message(self, format, *args):
            return

        def send_html(self, body: str):
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, payload: dict, status: int = 200):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_stream(self):
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()

            try:
                while True:
                    jpeg = state.camera.get_jpeg()
                    if jpeg is None:
                        time.sleep(0.05)
                        continue

                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                return

    return DriveHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser tank-drive test remote for RoboDriver.")
    parser.add_argument("--port", default=None, help="Arduino serial port, for example /dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
    parser.add_argument("--speed", type=int, default=DEFAULT_SPEED)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=CAMERA_SIZE[0])
    parser.add_argument("--height", type=int, default=CAMERA_SIZE[1])
    parser.add_argument("--fps", type=float, default=12.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ser = open_serial(args.port, args.baudrate)
    camera = CameraStream(args.camera_index, args.width, args.height, args.fps)
    camera.start()

    state = DriveState(ser, args.speed, camera)
    state.send(f"SPEED {state.speed}")
    state.send("READY")

    server = ThreadingHTTPServer(("0.0.0.0", args.web_port), make_handler(state))
    print(f"Open: http://{local_ip()}:{args.web_port}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.send("STOP")
        server.server_close()
        camera.stop()
        ser.close()


if __name__ == "__main__":
    main()
