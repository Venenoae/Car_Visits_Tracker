import os
import sys
import time
import queue
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import cv2
import requests

# ==============================================================================
# 🛠️ CONFIGURATION
# ==============================================================================
API_URL = "http://192.168.0.24:8000/api/capture"  # Your laptop backend URL
ZONE = "Zone A"                                  # 'Zone A' (Ground) or 'Zone B' (Basement)
CAMERA_INDEX = 0                                # 0 is standard for Logitech USB webcam
WEB_STREAM_PORT = 8080                          # Port to view live feed in browser

# Virtual Tripwires calibrated for outside street / ramp (percentages of frame height)
# TOP LINE: Distant street edge / upper ramp
TRIPWIRE_TOP_Y = 0.36
# BOTTOM LINE: Lower driveway / base of outside ramp (above indoor door sill)
TRIPWIRE_BOTTOM_Y = 0.58

# Mask out indoor showroom floor where staff walk (anything below y=0.64 is ignored)
DETECTION_Y_MIN = 0.30
DETECTION_Y_MAX = 0.64

# Contour area and width for distant cars outside (15-20 meters away through glass)
MIN_CONTOUR_AREA = 3200
MIN_VEHICLE_WIDTH = 75
CAPTURE_COOLDOWN = 12
CACHE_MAX_AGE_DAYS = 2  # Discard cached frames older than 2 days to protect SD card storage

# Local cache directory for offline resilience
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Upload queue
upload_queue = queue.Queue()

# Global variable to share the latest annotated frame with the web preview
latest_annotated_frame = None
frame_lock = threading.Lock()


# ==============================================================================
# 🌐 LIVE WEB PREVIEW STREAMER (PORT 8080)
# ==============================================================================
class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Gate Camera - {ZONE} Live Tracker</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        background: #090d16;
                        color: #f1f5f9;
                        display: flex;
                        flex-direction: column;
                        align-items: center;
                        padding: 20px;
                        margin: 0;
                    }}
                    h1 {{ color: #38bdf8; margin-bottom: 6px; }}
                    .tag {{
                        background: #1e293b;
                        color: #94a3b8;
                        padding: 4px 12px;
                        border-radius: 9999px;
                        font-size: 13px;
                        margin-bottom: 16px;
                    }}
                    .video-box {{
                        position: relative;
                        border: 3px solid #334155;
                        border-radius: 12px;
                        overflow: hidden;
                        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
                        max-width: 960px;
                        width: 100%;
                    }}
                    img {{
                        display: block;
                        width: 100%;
                        height: auto;
                    }}
                    .controls {{
                        margin-top: 18px;
                        display: flex;
                        gap: 16px;
                    }}
                    .badge {{
                        padding: 8px 16px;
                        border-radius: 8px;
                        font-size: 14px;
                        font-weight: 600;
                    }}
                    .top-tw {{ background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; }}
                    .bot-tw {{ background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid #22c55e; }}
                </style>
            </head>
            <body>
                <h1>🚗 Gate Camera: {ZONE}</h1>
                <div class="tag">Backend: {API_URL}</div>
                <div class="video-box">
                    <img src="/stream.mjpg" />
                </div>
                <div class="controls">
                    <span class="badge top-tw">Tripwire Top (Distant / Outside): {int(TRIPWIRE_TOP_Y*100)}%</span>
                    <span class="badge bot-tw">Tripwire Bottom (Close / Inside): {int(TRIPWIRE_BOTTOM_Y*100)}%</span>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))

        elif self.path == '/snapshot':
            with frame_lock:
                if latest_annotated_frame is None:
                    frame_bytes = None
                else:
                    ret, jpeg = cv2.imencode('.jpg', latest_annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    frame_bytes = jpeg.tobytes() if ret else None

            if frame_bytes:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(frame_bytes)))
                self.end_headers()
                self.wfile.write(frame_bytes)
            else:
                self.send_response(503)
                self.end_headers()

        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()

            while True:
                with frame_lock:
                    if latest_annotated_frame is None:
                        frame_bytes = None
                    else:
                        ret, jpeg = cv2.imencode('.jpg', latest_annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                        frame_bytes = jpeg.tobytes() if ret else None

                if frame_bytes:
                    try:
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(frame_bytes)))
                        self.end_headers()
                        self.wfile.write(frame_bytes)
                        self.wfile.write(b'\r\n')
                    except Exception:
                        break
                time.sleep(0.04)

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

def run_web_streamer():
    server = ThreadingHTTPServer(('0.0.0.0', WEB_STREAM_PORT), StreamHandler)
    server.serve_forever()


# ==============================================================================
# 🚀 BACKGROUND UPLOADER THREAD (OFFLINE-SAFE)
# ==============================================================================
def purge_expired_cache():
    """Removes cached frames older than CACHE_MAX_AGE_DAYS to protect Pi SD card storage"""
    cutoff = time.time() - (CACHE_MAX_AGE_DAYS * 86400)
    if not os.path.exists(CACHE_DIR):
        return
    for fn in os.listdir(CACHE_DIR):
        if fn.endswith(".jpg"):
            fp = os.path.join(CACHE_DIR, fn)
            try:
                import re
                from datetime import datetime
                m = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', fn)
                if m:
                    file_ts = datetime(*map(int, m.groups())).timestamp()
                else:
                    file_ts = os.path.getmtime(fp)

                if file_ts < cutoff:
                    os.remove(fp)
                    print(f"[Uploader] 🗑️ Discarded expired cache snapshot (> {CACHE_MAX_AGE_DAYS} days): {fn}")
            except Exception as e:
                pass


def uploader_worker():
    """Background worker that continuously uploads queued frames to FastAPI backend"""
    print("[Uploader] Background upload worker started.")
    purge_expired_cache()
    last_purge_time = time.time()
    
    # Check cache for any unsent frames on startup
    for fn in sorted(os.listdir(CACHE_DIR)):
        if fn.endswith(".jpg"):
            upload_queue.put(fn)

    while True:
        filename = None
        try:
            # Periodically purge cache every hour
            if time.time() - last_purge_time > 3600:
                purge_expired_cache()
                last_purge_time = time.time()

            filename = upload_queue.get()
            file_path = os.path.join(CACHE_DIR, filename)

            if not os.path.exists(file_path):
                upload_queue.task_done()
                continue

            # Check if this frame is older than 2 days
            cutoff = time.time() - (CACHE_MAX_AGE_DAYS * 86400)
            try:
                import re
                from datetime import datetime
                m = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', filename)
                file_ts = datetime(*map(int, m.groups())).timestamp() if m else os.path.getmtime(file_path)
                if file_ts < cutoff:
                    os.remove(file_path)
                    print(f"[Uploader] 🗑️ Skipped & purged expired frame: {filename}")
                    upload_queue.task_done()
                    continue
            except Exception:
                pass

            # Parse direction from filename: e.g. "ZoneA_Entry_20260923_205000.jpg"
            parts = filename.replace(".jpg", "").split("_")
            direction = parts[1] if len(parts) >= 2 else "Entry"

            print(f"[Uploader] Sending {direction} snapshot ({filename}) to backend...")
            payload = {"zone": ZONE, "direction": direction}

            with open(file_path, "rb") as img_file:
                files = {"file": (filename, img_file, "image/jpeg")}
                response = requests.post(API_URL, data=payload, files=files, timeout=12)

            if response.status_code == 200:
                print(f"[Uploader] ✅ Upload Successful! Dashboard updated for {direction}.")
                os.remove(file_path)
                upload_queue.task_done()
            else:
                print(f"[Uploader] ⚠️ Server returned HTTP {response.status_code}. Retrying in 10s...")
                time.sleep(10)
                upload_queue.put(filename)
                upload_queue.task_done()

        except requests.exceptions.RequestException:
            print("[Uploader] 📡 Network offline / Laptop unreachable. Frame safely kept in cache. Retrying in 15s...")
            if filename:
                upload_queue.put(filename)
                upload_queue.task_done()
            time.sleep(15)
        except Exception as e:
            print(f"[Uploader] Error: {e}")
            time.sleep(5)


# ==============================================================================
# 🎥 MAIN MOTION & DIRECTION DETECTION PIPELINE
# ==============================================================================
def main():
    global latest_annotated_frame

    # 1. Start background uploader thread
    uploader_thread = threading.Thread(target=uploader_worker, daemon=True)
    uploader_thread.start()

    # 2. Start web live streamer thread
    streamer_thread = threading.Thread(target=run_web_streamer, daemon=True)
    streamer_thread.start()
    print(f"\n[Preview] 🌐 Live camera preview available at: http://<RPI_IP>:{WEB_STREAM_PORT}/\n")

    # 3. Initialize Logitech Camera with MJPEG optimizations
    print(f"[Camera] Opening Logitech camera index {CAMERA_INDEX}...")
    try:
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)
    except Exception:
        cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        cap = cv2.VideoCapture(CAMERA_INDEX)

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)

    if not cap.isOpened():
        print(f"❌ Error: Could not open camera on index {CAMERA_INDEX}!")
        print("Check if webcam is plugged into USB 3.0 port and run: v4l2-ctl --list-devices")
        sys.exit(1)

    time.sleep(1)  # Warmup sensor
    print(f"✅ Camera initialized at 1280x720 (MJPG 30FPS).")
    print(f"📡 Monitoring '{ZONE}' gate triggers... Press Ctrl+C to stop.")

    # Background subtractor for robust moving object tracking
    back_sub = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=30, detectShadows=True)

    last_capture_time = 0
    top_trigger_time = 0
    bottom_trigger_time = 0
    last_status_msg = "Ready - Waiting for vehicle"

    # Centroid trajectory and close-zone best-plate buffer
    trajectory = []  # List of (timestamp, cy, area)
    best_vehicle_frame = None
    max_tracked_area = 0

    consecutive_failures = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            consecutive_failures += 1
            if consecutive_failures > 20:
                print(f"[Camera] Connection lost. Attempting to reconnect to camera index {CAMERA_INDEX}...")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(CAMERA_INDEX)
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                consecutive_failures = 0
            time.sleep(0.05)
            continue
        consecutive_failures = 0

        h, w, _ = frame.shape
        y_top = int(h * TRIPWIRE_TOP_Y)
        y_bottom = int(h * TRIPWIRE_BOTTOM_Y)
        y_roi_min = int(h * DETECTION_Y_MIN)
        y_roi_max = int(h * DETECTION_Y_MAX)

        # 1. Mask out indoor showroom floor where staff walk and distant sky
        # This completely prevents walking employees from ever triggering false alerts!
        motion_frame = frame.copy()
        motion_frame[:y_roi_min, :] = 0
        motion_frame[y_roi_max:, :] = 0

        # 2. Background Subtraction focused exclusively on outside driveway/ramp
        fg_mask = back_sub.apply(motion_frame)
        _, thresh = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_DILATE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        current_time = time.time()

        # Create display copy with annotations for live preview
        display_frame = frame.copy()

        # Draw Outdoor Street & Ramp Detection Corridor
        cv2.line(display_frame, (0, y_top), (w, y_top), (0, 0, 255), 2)  # Red: Top Line
        cv2.putText(display_frame, f"OUTSIDE RAMP / STREET TOP ({int(TRIPWIRE_TOP_Y*100)}%)", (20, y_top - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)

        cv2.line(display_frame, (0, y_bottom), (w, y_bottom), (0, 255, 0), 2)  # Green: Bottom Line
        cv2.putText(display_frame, f"OUTSIDE DRIVEWAY BASE ({int(TRIPWIRE_BOTTOM_Y*100)}%)", (20, y_bottom - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # Masked Floor Indicator
        cv2.line(display_frame, (0, y_roi_max), (w, y_roi_max), (100, 100, 100), 1)
        cv2.putText(display_frame, "[INDOOR FLOOR MASKED OUT - PEDESTRIANS IGNORED]", (20, y_roi_max + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 140, 140), 1)

        largest_area_this_frame = 0
        vehicle_box = None

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < MIN_CONTOUR_AREA:
                continue

            x, y, bw, bh = cv2.boundingRect(contour)

            # Ignore contours spanning outside the outdoor ROI
            if (y + bh) > (y_roi_max + 20) or y < (y_roi_min - 20):
                continue

            # Pedestrian filter: narrow upright contours
            aspect_ratio = bw / float(bh) if bh > 0 else 0
            if aspect_ratio < 0.55 and bw < 70:
                cv2.rectangle(display_frame, (x, y), (x + bw, y + bh), (120, 120, 120), 1)
                continue

            if bw < MIN_VEHICLE_WIDTH:
                continue

            if area > largest_area_this_frame:
                largest_area_this_frame = area
                vehicle_box = (x, y, bw, bh)

            # Draw moving vehicle bounding box
            cv2.rectangle(display_frame, (x, y), (x + bw, y + bh), (255, 200, 0), 2)

        # Track 2D trajectory (x, y) and best clear frame
        if vehicle_box is not None:
            x, y, bw, bh = vehicle_box
            cx = x + (bw // 2)
            cy = y + (bh // 2)
            trajectory.append((current_time, cx, cy, largest_area_this_frame))

            # Tripwire intersection triggers
            if y <= y_top <= (y + bh):
                top_trigger_time = current_time
            if y <= y_bottom <= (y + bh):
                bottom_trigger_time = current_time

            # Buffer clearest frame when vehicle has maximum clear size in outside zone
            if largest_area_this_frame > max_tracked_area:
                max_tracked_area = largest_area_this_frame
                best_vehicle_frame = frame.copy()

        # Prune trajectory to last 2.5 seconds
        trajectory = [t for t in trajectory if (current_time - t[0]) < 2.5]

        # Determine Motion Direction
        direction = None

        # 1. Dual Tripwire Intersection (Ramp Movement)
        if top_trigger_time > 0 and bottom_trigger_time > 0:
            if top_trigger_time < bottom_trigger_time and (bottom_trigger_time - top_trigger_time) < 4.0:
                direction = "Entry"
                last_status_msg = "🚗 Ramp Inward Motion -> CHECK-IN (Entry)"
            elif bottom_trigger_time < top_trigger_time and (top_trigger_time - bottom_trigger_time) < 4.0:
                direction = "Exit"
                last_status_msg = "🚙 Ramp Outward Motion -> CHECK-OUT (Exit)"
            top_trigger_time = 0
            bottom_trigger_time = 0

        # 2. Continuous 2D Centroid Vector (Vertical Ramp Crossing Only)
        elif len(trajectory) >= 5:
            dt = trajectory[-1][0] - trajectory[0][0]
            if dt >= 0.28:
                dx = trajectory[-1][1] - trajectory[0][1]
                dy = trajectory[-1][2] - trajectory[0][2]
                latest_y = trajectory[-1][2]
                initial_y = trajectory[0][2]

                # Movement must be primarily vertical (traveling down or up the entrance ramp)
                # AND must reach/originate from the showroom threshold line (y_bottom)
                # This guarantees that horizontal street traffic is NEVER mistaken for an entry or exit!
                if abs(dy) >= abs(dx) and abs(dy) > 35:
                    if dy > 35 and latest_y >= (y_bottom - 30):
                        direction = "Entry"
                        last_status_msg = "Ramp Inward Vector -> CHECK-IN (Entry)"
                    elif dy < -35 and initial_y >= (y_bottom - 30):
                        direction = "Exit"
                        last_status_msg = "Ramp Outward Vector -> CHECK-OUT (Exit)"
                elif abs(dx) > abs(dy) and abs(dx) > 50:
                    # Through street traffic passing horizontally - intentionally ignored
                    last_status_msg = "Street Cross Traffic Ignored (No Gate Crossing)"

        # Trigger snapshot upload if cooldown has passed
        if direction:
            if (current_time - last_capture_time) > CAPTURE_COOLDOWN:
                last_capture_time = current_time
                print(f"\n[EVENT] {last_status_msg}")

                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"{ZONE.replace(' ', '')}_{direction}_{timestamp}.jpg"
                save_path = os.path.join(CACHE_DIR, filename)

                # Save the highest-resolution buffered frame (vehicle closest to camera)
                upload_frame = best_vehicle_frame if best_vehicle_frame is not None else frame
                cv2.imwrite(save_path, upload_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                print(f"[Event] Captured best snapshot saved: {filename} (Contour Area: {max_tracked_area})")
                upload_queue.put(filename)

            # Reset trajectory and buffer after event
            trajectory = []
            best_vehicle_frame = None
            max_tracked_area = 0

        # Clear expired triggers (> 4 seconds)
        if current_time - top_trigger_time > 4.0:
            top_trigger_time = 0
        if current_time - bottom_trigger_time > 4.0:
            bottom_trigger_time = 0

        # If both tripwires idle and trajectory empty, reset best frame buffer
        if top_trigger_time == 0 and bottom_trigger_time == 0 and len(trajectory) == 0:
            best_vehicle_frame = None
            max_tracked_area = 0

        # Status overlay on preview
        overlay_msg = last_status_msg.encode("ascii", "ignore").decode().strip()
        cv2.putText(display_frame, f"STATUS: {overlay_msg}", (20, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Update frame for the web previewer
        with frame_lock:
            latest_annotated_frame = display_frame

    cap.release()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting gate tracker...")
        sys.exit(0)
