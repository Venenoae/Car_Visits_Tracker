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

# 🚗 ACTIVE DRIVEWAY CORRIDOR & PARKING MASK (New Camera Position Calibration)
# Horizontal Corridor:
# Left limit (x=0.28 / ~358px): Completely masks out the left showroom parking bay
# where the Nissan Patrol is parked so staff walking near it produce ZERO motion triggers!
# Right limit (x=0.96 / ~1228px): Covers the sliding glass door entrance on the right.
DETECTION_X_MIN = 0.28
DETECTION_X_MAX = 0.96

# Vertical Corridor:
# TOP LIMIT (y=0.18 / ~130px): Cuts off distant street traffic through outer glass.
# BOTTOM LIMIT (y=0.90 / ~648px): Extends down the showroom floor so entering SUVs
# are NOT clipped at y=490px (which previously inverted centroid dy and mislabeled Entry as Exit!).
DETECTION_Y_MIN = 0.18
DETECTION_Y_MAX = 0.90

# Virtual Tripwires calibrated for outside ramp to indoor bay (percentages of frame height)
# TOP LINE: Outer ramp / sliding glass door approach
TRIPWIRE_TOP_Y = 0.34
# BOTTOM LINE: Indoor bay floor past the white doorway sill (y=430px / 0.60)
TRIPWIRE_BOTTOM_Y = 0.58

# Contour area and width for real vehicles (rejects upright walking pedestrians)
MIN_CONTOUR_AREA = 14000
MIN_VEHICLE_WIDTH = 175
MIN_CENTROID_DISPLACEMENT = 75  # Vehicle must physically translate >= 75px to trigger
CAPTURE_COOLDOWN = 1.5          # 1.5s debounce between trigger uploads
CACHE_MAX_AGE_DAYS = 2          # Discard cached frames older than 2 days to protect SD card storage

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
    top_cross_down_time = 0
    bottom_cross_down_time = 0
    bottom_cross_up_time = 0
    top_cross_up_time = 0
    last_status_msg = "Ready - Monitoring Gate"

    # Centroid trajectory and close-zone best-plate buffer
    trajectory = []  # List of (timestamp, cx, cy, area, bw, bh, y_bottom_edge)
    best_vehicle_frame = None
    best_frame_quality = 0.0
    max_tracked_area = 0
    prev_cy = None

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
        x_lane_min = int(w * DETECTION_X_MIN)
        x_lane_max = int(w * DETECTION_X_MAX)

        # 1. Driveway Spatial Masking:
        # Zero out the left showroom parking bay (where the Nissan Patrol sits and staff walk),
        # the upper-left fixed glass wall & black structural pillar (x < 0.58*w, y < 0.57*h)
        # where cars cannot physically pass, the right wall/column, and the distant street.
        motion_frame = frame.copy()
        motion_frame[:y_roi_min, :] = 0
        motion_frame[y_roi_max:, :] = 0
        motion_frame[:, :x_lane_min] = 0
        motion_frame[:, x_lane_max:] = 0
        motion_frame[:int(h * 0.57), :int(w * 0.58)] = 0

        # 2. Background Subtraction focused exclusively on active sliding-door driveway
        fg_mask = back_sub.apply(motion_frame)
        _, thresh = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_DILATE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        current_time = time.time()

        # Create display copy with annotations for live preview
        display_frame = frame.copy()

        # Draw Dimmed Left Showroom Bay Overlay (Shows where movement is 100% ignored)
        overlay = display_frame.copy()
        cv2.rectangle(overlay, (0, 0), (x_lane_min, h), (20, 20, 20), -1)
        cv2.rectangle(overlay, (x_lane_max, 0), (w, h), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.40, display_frame, 0.60, 0, display_frame)

        cv2.line(display_frame, (x_lane_min, 0), (x_lane_min, h), (0, 165, 255), 2)
        cv2.putText(display_frame, "[SHOWROOM BAY MASKED]", (15, int(h * 0.45)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 140, 140), 1)

        # Active Driveway Lane HUD
        cv2.rectangle(display_frame, (x_lane_min, y_roi_min), (x_lane_max, y_roi_max), (0, 255, 255), 1)
        cv2.putText(display_frame, f"ACTIVE DRIVEWAY LANE [{int(DETECTION_X_MIN*100)}%-{int(DETECTION_X_MAX*100)}%]",
                    (x_lane_min + 10, y_roi_min - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # Draw Tripwires across active driveway lane
        top_color = (0, 0, 255) if (current_time - top_cross_down_time < 1.5 or current_time - top_cross_up_time < 1.5) else (0, 100, 255)
        bot_color = (0, 255, 0) if (current_time - bottom_cross_down_time < 1.5 or current_time - bottom_cross_up_time < 1.5) else (0, 200, 100)

        cv2.line(display_frame, (x_lane_min, y_top), (x_lane_max, y_top), top_color, 2)
        cv2.putText(display_frame, f"TRIPWIRE TOP (Ramp / Doorway) [{int(TRIPWIRE_TOP_Y*100)}%]", (x_lane_min + 10, y_top - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, top_color, 2)

        cv2.line(display_frame, (x_lane_min, y_bottom), (x_lane_max, y_bottom), bot_color, 2)
        cv2.putText(display_frame, f"TRIPWIRE BOTTOM (Gate Sill) [{int(TRIPWIRE_BOTTOM_Y*100)}%]", (x_lane_min + 10, y_bottom - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, bot_color, 2)

        # Masked Floor Indicator
        cv2.line(display_frame, (x_lane_min, y_roi_max), (x_lane_max, y_roi_max), (100, 100, 100), 1)
        cv2.putText(display_frame, "[LOWER EDGE OF GATE TRACKING ZONE]", (x_lane_min + 10, min(h - 10, y_roi_max + 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (140, 140, 140), 1)

        largest_area_this_frame = 0
        vehicle_box = None

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < MIN_CONTOUR_AREA:
                continue

            x, y, bw, bh = cv2.boundingRect(contour)

            # Ignore contours spanning outside the active driveway corridor
            if (y + bh) > (y_roi_max + 25) or y < (y_roi_min - 20):
                continue
            if (x + bw) > (x_lane_max + 20) or x < (x_lane_min - 20):
                continue

            # Strict Pedestrian & Floor Reflection Filter:
            # Staff walking in the showroom have bw=90..205px, bh=240..420px (aspect_ratio=0.33..0.70).
            # Real vehicles entering/exiting the sliding door have bw >= 220px or aspect_ratio >= 0.72 with large area.
            aspect_ratio = bw / float(bh) if bh > 0 else 0
            if (aspect_ratio < 0.72 and bw < 210 and area < 42000) or (bw < MIN_VEHICLE_WIDTH and area < 22000):
                cv2.rectangle(display_frame, (x, y), (x + bw, y + bh), (120, 120, 120), 1)
                continue

            if bw < MIN_VEHICLE_WIDTH:
                continue

            if area > largest_area_this_frame:
                largest_area_this_frame = area
                vehicle_box = (x, y, bw, bh)

            # Draw moving vehicle bounding box
            cv2.rectangle(display_frame, (x, y), (x + bw, y + bh), (255, 200, 0), 2)

        current_direction_hint = None

        # Track Centroid & Detect Crossing
        if vehicle_box is not None:
            x, y, bw, bh = vehicle_box
            cx = x + (bw // 2)
            cy = y + (bh // 2)
            y_bot_edge = y + bh

            # Spatial Continuity Check:
            # If the detected centroid suddenly jumps > 130px from the previous point,
            # it is a different physical object!
            if len(trajectory) > 0:
                last_time, last_cx, last_cy, _, _, _, _ = trajectory[-1]
                dist = ((cx - last_cx)**2 + (cy - last_cy)**2) ** 0.5
                if dist > 130 and (current_time - last_time) < 0.5:
                    trajectory = []
                    prev_cy = None
                    top_cross_down_time = 0
                    bottom_cross_down_time = 0
                    bottom_cross_up_time = 0
                    top_cross_up_time = 0

            trajectory.append((current_time, cx, cy, largest_area_this_frame, bw, bh, y_bot_edge))

            # Centroid tripwire crossings
            if prev_cy is not None:
                if prev_cy < y_top <= cy:
                    top_cross_down_time = current_time
                if prev_cy < y_bottom <= cy:
                    bottom_cross_down_time = current_time
                if prev_cy > y_bottom >= cy:
                    bottom_cross_up_time = current_time
                if prev_cy > y_top >= cy:
                    top_cross_up_time = current_time

            prev_cy = cy

            # Buffer clearest & sharpest frame when vehicle is well inside the doorway visibility zone
            v_crop_gray = cv2.cvtColor(frame[max(0, y):min(h, y + bh), max(0, x):min(w, x + bw)], cv2.COLOR_BGR2GRAY)
            sharpness = cv2.Laplacian(v_crop_gray, cv2.CV_64F).var() if v_crop_gray.size > 0 else 1.0
            centering_weight = 1.35 if (int(h * 0.52) <= y_bot_edge <= int(h * 0.88)) else 1.0
            frame_quality = largest_area_this_frame * (min(max(sharpness, 15.0), 400.0) ** 0.35) * centering_weight

            if frame_quality > best_frame_quality:
                best_frame_quality = frame_quality
                max_tracked_area = largest_area_this_frame
                best_vehicle_frame = frame.copy()

            # Draw Centroid & Trajectory trail
            cv2.circle(display_frame, (cx, cy), 6, (0, 255, 255), -1)
        else:
            prev_cy = None

        # Prune trajectory to last 3.5 seconds
        trajectory = [t for t in trajectory if (current_time - t[0]) < 3.5]

        # Draw trajectory history on preview
        if len(trajectory) > 1:
            for i in range(1, len(trajectory)):
                pt1 = (int(trajectory[i-1][1]), int(trajectory[i-1][2]))
                pt2 = (int(trajectory[i][1]), int(trajectory[i][2]))
                cv2.line(display_frame, pt1, pt2, (0, 255, 255), 2)

        # Determine Motion Direction
        direction = None

        start_cy = trajectory[0][2] if len(trajectory) > 0 else None
        start_cx = trajectory[0][1] if len(trajectory) > 0 else None

        # 1. Centroid Sequential Tripwires
        if top_cross_down_time > 0 and bottom_cross_down_time > 0:
            if top_cross_down_time < bottom_cross_down_time and (bottom_cross_down_time - top_cross_down_time) < 3.5:
                if start_cy is None or start_cy <= (y_top + 45):
                    direction = "Entry"
                    last_status_msg = "Top-to-Bottom Ramp Crossing -> ENTRY (Check-In)"
                else:
                    last_status_msg = "Indoor Motion Ignored (Did not originate from outside ramp)"
                top_cross_down_time = 0
                bottom_cross_down_time = 0
        elif bottom_cross_up_time > 0 and top_cross_up_time > 0:
            if bottom_cross_up_time < top_cross_up_time and (top_cross_up_time - bottom_cross_up_time) < 3.5:
                if start_cy is None or start_cy >= (y_bottom - 45):
                    direction = "Exit"
                    last_status_msg = "Bottom-to-Top Ramp Crossing -> EXIT (Check-Out)"
                else:
                    last_status_msg = "Ramp Outward Motion Ignored"
                bottom_cross_up_time = 0
                top_cross_up_time = 0

        # 2. Continuous 2D Motion Vector + Lower Bumper Advancement + Scale Factor
        if direction is None and len(trajectory) >= 5:
            dt = trajectory[-1][0] - trajectory[0][0]
            if dt >= 0.25:
                start_pts = trajectory[:2]
                end_pts = trajectory[-2:]

                s_cx = sum(p[1] for p in start_pts) / len(start_pts)
                s_cy = sum(p[2] for p in start_pts) / len(start_pts)
                s_area = sum(p[3] for p in start_pts) / len(start_pts)
                s_ybot = sum(p[6] for p in start_pts) / len(start_pts)

                end_cx = sum(p[1] for p in end_pts) / len(end_pts)
                end_cy = sum(p[2] for p in end_pts) / len(end_pts)
                end_area = sum(p[3] for p in end_pts) / len(end_pts)
                end_ybot = sum(p[6] for p in end_pts) / len(end_pts)

                dx = end_cx - s_cx
                dy = end_cy - s_cy
                dy_bot = end_ybot - s_ybot
                area_ratio = end_area / max(s_area, 1.0)

                # Filter out pure horizontal outside street traffic (high up in frame y < y_top)
                if abs(dx) > (abs(dy) * 1.8) and end_ybot < y_bottom:
                    last_status_msg = "Street Cross Traffic Ignored (Horizontal)"
                else:
                    # ENTRY: Vehicle moves downward into showroom (dy > 25 or dy_bot > 35)
                    # and approaches from the right-side sliding door (dx <= 20)
                    if (dy > 25 or dy_bot > 40) and dx <= 25 and (s_cy <= y_bottom + 20):
                        current_direction_hint = "Entry"
                        if (top_cross_down_time > 0) or (bottom_cross_down_time > 0) or (end_ybot >= y_bottom + 30 and area_ratio >= 1.05):
                            direction = "Entry"
                            last_status_msg = f"Ramp Inward Vector (dy=+{int(dy)}px, dy_bot=+{int(dy_bot)}px, scale={area_ratio:.2f}) -> ENTRY"

                    # EXIT: Vehicle moves upward toward the sliding door (dy < -25 and dy_bot < -20)
                    elif dy < -25 and dy_bot < -15 and (s_ybot >= y_bottom - 10):
                        current_direction_hint = "Exit"
                        if (bottom_cross_up_time > 0) or (top_cross_up_time > 0) or (area_ratio <= 0.95 and end_cy <= (y_top + 35)):
                            direction = "Exit"
                            last_status_msg = f"Ramp Outward Vector (dy={int(dy)}px, dy_bot={int(dy_bot)}px, scale={area_ratio:.2f}) -> EXIT"

        # Draw Real-time Direction Arrow HUD on Preview
        if current_direction_hint == "Entry" or direction == "Entry":
            cv2.arrowedLine(display_frame, (w - 100, 60), (w - 100, 160), (0, 255, 0), 5, tipLength=0.3)
            cv2.putText(display_frame, "ENTERING", (w - 180, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        elif current_direction_hint == "Exit" or direction == "Exit":
            cv2.arrowedLine(display_frame, (w - 100, 160), (w - 100, 60), (255, 200, 0), 5, tipLength=0.3)
            cv2.putText(display_frame, "EXITING", (w - 170, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)

        # Trigger snapshot upload if cooldown has passed and vehicle physically moved
        if direction:
            # 2D Displacement Validation: ensure vehicle translated >= MIN_CENTROID_DISPLACEMENT
            total_disp = 0
            if len(trajectory) >= 2:
                dx_tot = trajectory[-1][1] - trajectory[0][1]
                dy_tot = trajectory[-1][2] - trajectory[0][2]
                total_disp = (dx_tot**2 + dy_tot**2) ** 0.5

            if total_disp < MIN_CENTROID_DISPLACEMENT and len(trajectory) >= 4:
                direction = None
                last_status_msg = f"Stationary Car Activity Ignored (Displacement {int(total_disp)}px < {MIN_CENTROID_DISPLACEMENT}px)"

        if direction:
            if (current_time - last_capture_time) > CAPTURE_COOLDOWN:
                last_capture_time = current_time
                print(f"\n[EVENT] 🚀 {last_status_msg}")

                msec = int((current_time % 1) * 1000)
                timestamp = time.strftime("%Y%m%d_%H%M%S") + f"_{msec:03d}"
                filename = f"{ZONE.replace(' ', '')}_{direction}_{timestamp}.jpg"
                save_path = os.path.join(CACHE_DIR, filename)

                # Save the highest-resolution & sharpest buffered frame
                upload_frame = best_vehicle_frame if best_vehicle_frame is not None else frame
                cv2.imwrite(save_path, upload_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                print(f"[Event] Best snapshot saved: {filename} (Area: {max_tracked_area})")
                upload_queue.put(filename)

            # Reset trajectory and buffer after event
            trajectory = []
            best_vehicle_frame = None
            best_frame_quality = 0.0
            max_tracked_area = 0
            top_cross_down_time = 0
            bottom_cross_down_time = 0
            bottom_cross_up_time = 0
            top_cross_up_time = 0

        # Clear expired triggers (> 4 seconds)
        if current_time - top_cross_down_time > 4.0:
            top_cross_down_time = 0
        if current_time - bottom_cross_down_time > 4.0:
            bottom_cross_down_time = 0
        if current_time - bottom_cross_up_time > 4.0:
            bottom_cross_up_time = 0
        if current_time - top_cross_up_time > 4.0:
            top_cross_up_time = 0

        # If idle, reset best frame buffer
        if len(trajectory) == 0 and top_cross_down_time == 0 and bottom_cross_up_time == 0:
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
