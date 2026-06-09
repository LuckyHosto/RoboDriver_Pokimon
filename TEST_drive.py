import argparse
import html
import json
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

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

COMMANDS = {
    "forward": "FORWARD",
    "backward": "BACKWARD",
    "left": "TURN_LEFT",
    "right": "TURN_RIGHT",
    "stop": "STOP",
}

HTML_PAGE = """<!doctype html>
<html lang="ru">
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
      min-height: 100vh;
      display: grid;
      place-items: center;
    }
    main {
      width: min(92vw, 560px);
      display: grid;
      gap: 18px;
    }
    h1 {
      margin: 0;
      font-size: 28px;
      text-align: center;
    }
    .panel {
      background: #1b2028;
      border: 1px solid #303744;
      border-radius: 8px;
      padding: 18px;
      display: grid;
      gap: 16px;
    }
    .pad {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      grid-template-rows: repeat(3, 96px);
      gap: 12px;
    }
    button {
      border: 0;
      border-radius: 8px;
      background: #2e3745;
      color: #fff;
      font-size: 22px;
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
      gap: 8px;
      font-size: 16px;
    }
    input[type="range"] {
      width: 100%;
    }
    .status {
      min-height: 24px;
      color: #aeb8c8;
      font-family: Consolas, monospace;
      word-break: break-word;
    }
  </style>
</head>
<body>
  <main>
    <h1>RoboDriver TEST Drive</h1>
    <section class="panel">
      <div class="pad">
        <button class="forward" data-cmd="forward">Вперёд</button>
        <button class="left" data-cmd="left">Влево</button>
        <button class="stop" data-cmd="stop">STOP</button>
        <button class="right" data-cmd="right">Вправо</button>
        <button class="backward" data-cmd="backward">Назад</button>
      </div>
      <label>
        Скорость: <span id="speedValue">155</span>
        <input id="speed" type="range" min="0" max="255" value="155">
      </label>
      <div id="status" class="status">Готово</div>
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


class DriveState:
    def __init__(self, ser: serial.Serial, speed: int):
        self.ser = ser
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

    return DriveHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser tank-drive test remote for RoboDriver.")
    parser.add_argument("--port", default=None, help="Arduino serial port, for example /dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
    parser.add_argument("--speed", type=int, default=DEFAULT_SPEED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ser = open_serial(args.port, args.baudrate)
    state = DriveState(ser, args.speed)
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
        ser.close()


if __name__ == "__main__":
    main()
