import os
import sys
import time
import socket
import threading
import cv2
import numpy as np
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Tripwire percentages
TRIPWIRE_1_Y = 0.3
TRIPWIRE_2_Y = 0.7

CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", 0))

# Shared frame state
latest_frame = None
latest_jpeg = None
frame_lock = threading.Lock()
running = True

def is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) != 0

def resolve_port() -> int:
    env_port = os.environ.get("CAMERA_PORT")
    if env_port:
        return int(env_port)
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        return int(sys.argv[1])
    # Port 8080 is often used; check 8080 then fallback to 8081
    if is_port_available(8080):
        return 8080
    for candidate in [8081, 8085, 8088, 8090, 8888]:
        if is_port_available(candidate):
            return candidate
    return 8081

PORT = resolve_port()


def camera_worker():
    global latest_frame, latest_jpeg, running
    
    cap = None
    try:
        if sys.platform.startswith('win'):
            cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(CAMERA_INDEX)
            
        if not cap.isOpened():
            cap = cv2.VideoCapture(CAMERA_INDEX)
            
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        print(f"[Camera] Hardware camera initialized at index {CAMERA_INDEX}")
    except Exception as e:
        print(f"[Camera] Notice initializing camera: {e}")

    while running:
        frame = None
        if cap and cap.isOpened():
            ret, captured = cap.read()
            if ret and captured is not None:
                frame = captured

        if frame is None:
            # Generate simulated calibration test pattern if hardware camera is not available
            h, w = 720, 1280
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            for y in range(h):
                val = int(18 + 20 * (y / h))
                frame[y, :] = (val, val, val + 15)
            
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, f"GATE CAMERA FEED (SIMULATED)", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (56, 189, 248), 2)
            cv2.putText(frame, "Waiting for hardware stream or aim calibration...", (40, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (148, 163, 184), 2)
            cv2.putText(frame, now_str, (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 116, 139), 1)

        h, w, _ = frame.shape
        y1 = int(h * TRIPWIRE_1_Y)
        y2 = int(h * TRIPWIRE_2_Y)

        # Draw Tripwires
        cv2.line(frame, (0, y1), (w, y1), (0, 0, 255), 3)  # Red: TW 1
        cv2.putText(frame, "TRIPWIRE 1 (OUTSIDE - 30%)", (24, y1 - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        cv2.line(frame, (0, y2), (w, y2), (0, 255, 0), 3)  # Green: TW 2
        cv2.putText(frame, "TRIPWIRE 2 (INSIDE - 70%)", (24, y2 - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # Timestamp overlay
        now_str = time.strftime("%H:%M:%S")
        cv2.putText(frame, f"LIVE: {now_str}", (w - 200, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (34, 197, 94), 2)

        ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if ret:
            with frame_lock:
                latest_frame = frame
                latest_jpeg = jpeg.tobytes()

        time.sleep(0.033)

    if cap:
        cap.release()


class VideoStreamHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy GET log spam for stream chunks
        if "/stream.mjpg" not in str(format % args):
            super().log_message(format, *args)

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>📷 Gate Camera Calibration & Live Preview</title>
                <style>
                    * {{ box-sizing: border-box; }}
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        background: #090d16;
                        color: #f8fafc;
                        display: flex;
                        flex-direction: column;
                        align-items: center;
                        padding: 24px;
                        margin: 0;
                        min-height: 100vh;
                    }}
                    .header {{
                        text-align: center;
                        margin-bottom: 20px;
                    }}
                    h1 {{
                        color: #38bdf8;
                        margin: 0 0 8px 0;
                        font-size: 1.85rem;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        gap: 10px;
                    }}
                    p {{
                        color: #94a3b8;
                        margin: 0;
                        font-size: 0.95rem;
                    }}
                    .video-container {{
                        position: relative;
                        width: 100%;
                        max-width: 980px;
                        border: 2px solid rgba(56, 189, 248, 0.35);
                        border-radius: 14px;
                        overflow: hidden;
                        background: #000;
                        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8), 0 0 25px rgba(56, 189, 248, 0.15);
                    }}
                    img.stream {{
                        display: block;
                        width: 100%;
                        height: auto;
                        aspect-ratio: 16 / 9;
                        object-fit: cover;
                    }}
                    .controls {{
                        display: flex;
                        flex-wrap: wrap;
                        gap: 14px;
                        margin-top: 20px;
                        align-items: center;
                        justify-content: center;
                    }}
                    .badge {{
                        padding: 8px 16px;
                        border-radius: 8px;
                        font-weight: 600;
                        font-size: 13.5px;
                        display: flex;
                        align-items: center;
                        gap: 8px;
                    }}
                    .red {{
                        background: rgba(239, 68, 68, 0.15);
                        color: #f87171;
                        border: 1px solid rgba(239, 68, 68, 0.4);
                    }}
                    .green {{
                        background: rgba(34, 197, 94, 0.15);
                        color: #4ade80;
                        border: 1px solid rgba(34, 197, 94, 0.4);
                    }}
                    .btn {{
                        background: rgba(255, 255, 255, 0.08);
                        color: #38bdf8;
                        border: 1px solid rgba(56, 189, 248, 0.3);
                        padding: 8px 18px;
                        border-radius: 8px;
                        text-decoration: none;
                        font-size: 13.5px;
                        font-weight: 600;
                        cursor: pointer;
                        transition: all 0.2s ease;
                    }}
                    .btn:hover {{
                        background: rgba(56, 189, 248, 0.2);
                        transform: translateY(-1px);
                    }}
                    .status-bar {{
                        margin-top: 14px;
                        font-size: 12.5px;
                        color: #64748b;
                    }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📷 Gate Camera Live Calibration Feed</h1>
                    <p>Live video feed with tripwires for gate alignment and license plate capture</p>
                </div>
                
                <div class="video-container">
                    <img class="stream" src="/stream.mjpg" alt="Live Gate Camera Stream" />
                </div>
                
                <div class="controls">
                    <span class="badge red">● Tripwire 1 (Outside Gate - 30%)</span>
                    <span class="badge green">● Tripwire 2 (Inside Workshop - 70%)</span>
                    <a href="/snapshot" target="_blank" class="btn">Capture Snapshot</a>
                    <a href="http://localhost:5173/" class="btn">Return to Dashboard</a>
                </div>
                
                <div class="status-bar">
                    Port: {PORT} | Camera Index: {CAMERA_INDEX} | Stream format: MJPEG (HTTP)
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))

        elif self.path == '/snapshot':
            with frame_lock:
                jpg = latest_jpeg
            if jpg:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(jpg)))
                self.send_header('Cache-Control', 'no-cache, no-store')
                self.end_headers()
                self.wfile.write(jpg)
            else:
                self.send_response(503)
                self.end_headers()

        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-cache, private, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()

            try:
                while running:
                    with frame_lock:
                        jpg = latest_jpeg
                    if jpg:
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(jpg)))
                        self.end_headers()
                        self.wfile.write(jpg)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError, Exception):
                pass
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    # Start background camera capture thread
    cam_thread = threading.Thread(target=camera_worker, daemon=True)
    cam_thread.start()

    print(f"Starting Camera Calibration Web Server on http://0.0.0.0:{PORT}...")
    print(f"Direct stream URL: http://127.0.0.1:{PORT}/stream.mjpg")
    print(f"Live preview UI:   http://127.0.0.1:{PORT}/")

    server = ThreadingHTTPServer(('0.0.0.0', PORT), VideoStreamHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping camera server...")
        running = False
        server.server_close()
