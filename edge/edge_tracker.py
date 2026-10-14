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

# Virtual Tripwires calibrated for outside ramp to indoor bay (percentages of frame height)
# TOP LINE: Outer ramp / glass door sill
TRIPWIRE_TOP_Y = 0.34
# BOTTOM LINE: Indoor bay floor where car enters and stops
TRIPWIRE_BOTTOM_Y = 0.52

# Detection corridor:
# From top ramp (y=0.18) down to car stop position (y=0.65). 
# Anything below y=0.65 is staff walking floor and is completely masked out.
DETECTION_Y_MIN = 0.18
DETECTION_Y_MAX = 0.65

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
    top_cross_down_time = 0
    bottom_cross_down_time = 0
    bottom_cross_up_time = 0
    top_cross_up_time = 0
    last_status_msg = "Ready - Monitoring Gate"

    # Centroid trajectory and close-zone best-plate buffer
    trajectory = []  # List of (timestamp, cx, cy, area, bw, bh)
    best_vehicle_frame = None
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

        # 1. Mask out indoor showroom floor where staff walk and distant sky
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

        # Draw Outdoor Street & Ramp Detection Corridor with active status
        top_color = (0, 0, 255) if (current_time - top_cross_down_time < 1.5 or current_time - top_cross_up_time < 1.5) else (0, 100, 255)
        bot_color = (0, 255, 0) if (current_time - bottom_cross_down_time < 1.5 or current_time - bottom_cross_up_time < 1.5) else (0, 200, 100)

        cv2.line(display_frame, (0, y_top), (w, y_top), top_color, 2)
        cv2.putText(display_frame, f"TRIPWIRE TOP (Ramp / Street) [{int(TRIPWIRE_TOP_Y*100)}%]", (20, y_top - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, top_color, 2)

        cv2.line(display_frame, (0, y_bottom), (w, y_bottom), bot_color, 2)
        cv2.putText(display_frame, f"TRIPWIRE BOTTOM (Gate Threshold) [{int(TRIPWIRE_BOTTOM_Y*100)}%]", (20, y_bottom - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, bot_color, 2)

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

        current_direction_hint = None

        # Track Centroid & Detect Crossing
        if vehicle_box is not None:
            x, y, bw, bh = vehicle_box
            cx = x + (bw // 2)
            cy = y + (bh // 2)
            trajectory.append((current_time, cx, cy, largest_area_this_frame, bw, bh))

            # Centroid tripwire crossings (precise point-crossing avoids multi-line overlap)
            if prev_cy is not None:
                # Downward crossing across Top line
                if prev_cy < y_top <= cy:
                    top_cross_down_time = current_time
                # Downward crossing across Bottom line
                if prev_cy < y_bottom <= cy:
                    bottom_cross_down_time = current_time
                # Upward crossing across Bottom line
                if prev_cy > y_bottom >= cy:
                    bottom_cross_up_time = current_time
                # Upward crossing across Top line
                if prev_cy > y_top >= cy:
                    top_cross_up_time = current_time

            prev_cy = cy

            # Buffer clearest frame when vehicle has maximum clear size in outside zone
            if largest_area_this_frame > max_tracked_area:
                max_tracked_area = largest_area_this_frame
                best_vehicle_frame = frame.copy()

            # Draw Centroid & Trajectory trail
            cv2.circle(display_frame, (cx, cy), 6, (0, 255, 255), -1)
        else:
            prev_cy = None

        # Prune trajectory to last 3.0 seconds
        trajectory = [t for t in trajectory if (current_time - t[0]) < 3.0]

        # Draw trajectory history on preview
        if len(trajectory) > 1:
            for i in range(1, len(trajectory)):
                pt1 = (int(trajectory[i-1][1]), int(trajectory[i-1][2]))
                pt2 = (int(trajectory[i][1]), int(trajectory[i][2]))
                cv2.line(display_frame, pt1, pt2, (0, 255, 255), 2)

        # Determine Motion Direction
        direction = None

        # 1. Centroid Sequential Tripwires
        # Top -> Down crossing within 0.3s - 3.5s = ENTRY
        if top_cross_down_time > 0 and bottom_cross_down_time > 0:
            if top_cross_down_time < bottom_cross_down_time and (bottom_cross_down_time - top_cross_down_time) < 3.5:
                direction = "Entry"
                last_status_msg = "Top-to-Bottom Crossing -> ENTRY (Check-In)"
                top_cross_down_time = 0
                bottom_cross_down_time = 0
        # Bottom -> Top crossing within 0.3s - 3.5s = EXIT
        elif bottom_cross_up_time > 0 and top_cross_up_time > 0:
            if bottom_cross_up_time < top_cross_up_time and (top_cross_up_time - bottom_cross_up_time) < 3.5:
                direction = "Exit"
                last_status_msg = "Bottom-to-Top Crossing -> EXIT (Check-Out)"
                bottom_cross_up_time = 0
                top_cross_up_time = 0

        # 2. Continuous 2D Motion Vector + Perspective Scale Factor (Fallback / Real-Time)
        if direction is None and len(trajectory) >= 6:
            dt = trajectory[-1][0] - trajectory[0][0]
            if dt >= 0.28:
                # Compare average of first 3 points vs last 3 points for smooth vector
                start_pts = trajectory[:3]
                end_pts = trajectory[-3:]

                start_cx = sum(p[1] for p in start_pts) / len(start_pts)
                start_cy = sum(p[2] for p in start_pts) / len(start_pts)
                start_area = sum(p[3] for p in start_pts) / len(start_pts)

                end_cx = sum(p[1] for p in end_pts) / len(end_pts)
                end_cy = sum(p[2] for p in end_pts) / len(end_pts)
                end_area = sum(p[3] for p in end_pts) / len(end_pts)

                dx = end_cx - start_cx
                dy = end_cy - start_cy
                area_ratio = end_area / max(start_area, 1.0)

                # Filter out horizontal street cross-traffic
                if abs(dx) > (abs(dy) * 1.3) and abs(dx) > 40:
                    last_status_msg = "Street Cross Traffic Ignored (Horizontal)"
                else:
                    # Vertical motion down ramp / driveway
                    if dy > 30:
                        # Moving Top -> Down (Approaching camera)
                        current_direction_hint = "Entry"
                        # Confirmed entry if: crossed top downward, or area enlarged, or reached gate base
                        if (top_cross_down_time > 0) or (area_ratio >= 1.05) or (end_cy >= (y_bottom - 20)):
                            direction = "Entry"
                            last_status_msg = f"Vector Down (dy=+{int(dy)}px, scale={area_ratio:.2f}) -> ENTRY"

                    elif dy < -30:
                        # Moving Down -> Top (Leaving camera)
                        current_direction_hint = "Exit"
                        # Confirmed exit if: crossed bottom upward, or area shrank, or started near gate base
                        if (bottom_cross_up_time > 0) or (area_ratio <= 0.95) or (start_cy >= (y_bottom - 20)):
                            direction = "Exit"
                            last_status_msg = f"Vector Up (dy={int(dy)}px, scale={area_ratio:.2f}) -> EXIT"

        # Draw Real-time Direction Arrow HUD on Preview
        if current_direction_hint == "Entry" or direction == "Entry":
            cv2.arrowedLine(display_frame, (w - 100, 60), (w - 100, 160), (0, 255, 0), 5, tipLength=0.3)
            cv2.putText(display_frame, "ENTERING", (w - 180, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        elif current_direction_hint == "Exit" or direction == "Exit":
            cv2.arrowedLine(display_frame, (w - 100, 160), (w - 100, 60), (255, 200, 0), 5, tipLength=0.3)
            cv2.putText(display_frame, "EXITING", (w - 170, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)

        # Trigger snapshot upload if cooldown has passed
        if direction:
            if (current_time - last_capture_time) > CAPTURE_COOLDOWN:
                last_capture_time = current_time
                print(f"\n[EVENT] 🚀 {last_status_msg}")

                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"{ZONE.replace(' ', '')}_{direction}_{timestamp}.jpg"
                save_path = os.path.join(CACHE_DIR, filename)

                # Save the highest-resolution buffered frame (vehicle closest to camera)
                upload_frame = best_vehicle_frame if best_vehicle_frame is not None else frame
                cv2.imwrite(save_path, upload_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                print(f"[Event] Best snapshot saved: {filename} (Area: {max_tracked_area})")
                upload_queue.put(filename)

            # Reset trajectory and buffer after event
            trajectory = []
            best_vehicle_frame = None
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
