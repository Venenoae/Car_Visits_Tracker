import os
import re
import shutil
import anyio
from datetime import datetime, date
from typing import List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv

from fastapi import FastAPI, Depends, File, UploadFile, Form, HTTPException, status, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import engine, Base, get_db, User, Vehicle, Visit
from auth import verify_password, get_password_hash, create_access_token, get_current_user, init_admin_user
from ai_pipeline import run_ai_pipeline, normalize_plate_number

# Load environment variables
load_dotenv()

# Initialize FastAPI App
app = FastAPI(title="Vehicle Visits Tracker API", version="1.0.0")

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local testing; narrow down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Upload directory setup
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Serve uploaded images statically
app.mount("/static/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/api/static/uploads", StaticFiles(directory=UPLOADS_DIR), name="api_uploads")


@app.get("/", response_class=HTMLResponse)
def root_index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vehicle Visits Tracker API</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #090d16; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }
            .card { background: rgba(30, 41, 59, 0.85); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 2.5rem 3rem; max-width: 520px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.7); }
            h1 { color: #38bdf8; margin-top: 0; font-size: 1.75rem; }
            p { color: #94a3b8; font-size: 0.95rem; line-height: 1.5; margin-bottom: 2rem; }
            .btn { display: inline-block; padding: 0.85rem 1.75rem; border-radius: 8px; font-weight: 600; text-decoration: none; margin: 0.5rem; transition: all 0.2s; }
            .btn-primary { background: linear-gradient(135deg, #0284c7 0%, #2563eb 100%); color: #fff; box-shadow: 0 4px 15px rgba(2, 132, 199, 0.4); }
            .btn-secondary { background: rgba(255, 255, 255, 0.08); color: #cbd5e1; border: 1px solid rgba(255, 255, 255, 0.15); }
            .btn:hover { transform: translateY(-2px); }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🚗 CallMyCar API Server</h1>
            <p>The FastAPI backend server is active and running. To open the real-time visual tracking dashboard, click below:</p>
            <a href="http://localhost:5173/" class="btn btn-primary">Open Web Dashboard (Port 5173)</a>
            <br />
            <a href="/docs" class="btn btn-secondary">API Documentation (/docs)</a>
        </div>
    </body>
    </html>
    """


# --- STARTUP HOOK ---
@app.on_event("startup")
def startup_event():
    # Automatically create tables in local MySQL if they don't exist
    Base.metadata.create_all(bind=engine)
    # Initialize the default admin user
    db = next(get_db())
    init_admin_user(db)
    # Preload AI models to prevent first-request lag
    from ai_pipeline import init_models
    init_models()
    
    # Start periodic 6-hour storage cleanup loop
    import asyncio
    from maintenance import cleanup_old_images
    from database import SessionLocal

    async def scheduled_cleanup_loop():
        # Short initial delay to let server boot
        await asyncio.sleep(10)
        while True:
            try:
                db_clean = SessionLocal()
                try:
                    cleanup_old_images(db_clean)
                finally:
                    db_clean.close()
            except Exception as e:
                print(f"[Maintenance] Scheduled cleanup error: {e}")
            await asyncio.sleep(6 * 3600)

    asyncio.create_task(scheduled_cleanup_loop())


# --- WEBSOCKET EVENT MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WS] Client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"[WS] Broadcast failed for client: {e}")
                # Connection might be dead, but we handle cleanup on disconnect

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive by reading message
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# --- AUTHENTICATION ENDPOINTS ---

@app.post("/api/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


# --- CORE CAPTURE & AI PIPELINE ---

async def process_capture_background(
    scan_id: str,
    zone: str,
    direction: str,
    file_path: str,
    relative_img_url: str,
    timestamp_str: str
):
    """
    Background worker that runs YOLO & EasyOCR, updates the DB, 
    and broadcasts the final state to the dashboard.
    """
    try:
        # Offload CPU-heavy AI processing to a separate thread pool so the event loop doesn't hang
        ai_results = await anyio.to_thread.run_sync(run_ai_pipeline, file_path)
    except Exception as e:
        print(f"[AI Background] Pipeline processing error: {e}")
        await manager.broadcast({
            "event_type": "SCAN_FAIL",
            "scan_id": scan_id,
            "detail": f"AI Engine exception: {str(e)}"
        })
        return

    if not ai_results["success"] or ai_results.get("plate") == "UNKNOWN":
        # Check if a vehicle exit occurred where the plate could not be read (e.g. reverse exit, obscured rear plate)
        if direction == "Exit" and ai_results.get("vehicle_detected"):
            from database import SessionLocal, Vehicle, Visit
            db_unverified = SessionLocal()
            try:
                active_inside = db_unverified.query(Visit).filter(Visit.zone == zone, Visit.status == "Inside").all()
                if not active_inside:
                    active_inside = db_unverified.query(Visit).filter(Visit.status == "Inside").all()

                candidates = []
                for v in active_inside:
                    veh = db_unverified.query(Vehicle).filter(Vehicle.plate_number == v.plate_number).first()
                    candidates.append({
                        "visit_id": v.id,
                        "plate_number": v.plate_number,
                        "zone": v.zone,
                        "entry_time": v.entry_timestamp.isoformat() if v.entry_timestamp else None,
                        "color": veh.color if veh else "Unknown",
                        "brand": veh.brand if veh else "Unknown"
                    })

                await manager.broadcast({
                    "event_type": "UNVERIFIED_EXIT",
                    "scan_id": scan_id,
                    "zone": zone,
                    "direction": "Exit",
                    "image_url": relative_img_url,
                    "detected_color": ai_results.get("color", "Unknown"),
                    "detected_brand": ai_results.get("brand", "Unknown"),
                    "timestamp": datetime.now().isoformat(),
                    "candidates": candidates
                })
                print(f"[AI Exit] ⚠️ Unverified exit broadcasted for {zone} ({len(candidates)} inside candidate vehicles).")
                return
            finally:
                db_unverified.close()

        # If vehicle detected on Entry but plate was unreadable/obscured:
        elif direction == "Entry" and ai_results.get("vehicle_detected"):
            # Spatial-Temporal Best-Shot Ingestion:
            # Check if an existing unreadable visit was recorded within the 8-second burst window
            from database import SessionLocal, Vehicle, Visit
            db_check = SessionLocal()
            try:
                current_chk = datetime.now()
                recent_unreadable = db_check.query(Visit).filter(
                    Visit.zone == zone,
                    Visit.status == "Inside",
                    (Visit.plate_number.like("UNREADABLE-%") | Visit.plate_number.like("CAR-%"))
                ).order_by(Visit.id.desc()).first()

                if recent_unreadable:
                    diff_sec = (current_chk - recent_unreadable.entry_timestamp).total_seconds()
                    if diff_sec < 8.0:
                        print(f"[AI Best-Shot] Burst frame arrived ({diff_sec:.1f}s ago). Refreshing best image for {recent_unreadable.plate_number}.")
                        recent_unreadable.entry_image_url = relative_img_url
                        new_brand = ai_results.get("brand")
                        new_color = ai_results.get("color")
                        veh = db_check.query(Vehicle).filter(Vehicle.plate_number == recent_unreadable.plate_number).first()
                        if veh:
                            if new_brand and new_brand != "Unknown":
                                veh.brand = new_brand
                            if new_color and new_color != "Unknown":
                                veh.color = new_color
                        db_check.commit()
                        await manager.broadcast({
                            "event_type": "SCAN_SUCCESS",
                            "scan_id": scan_id,
                            "zone": zone,
                            "plate": recent_unreadable.plate_number,
                            "direction": direction,
                            "color": veh.color if veh else "Unknown",
                            "brand": veh.brand if veh else "Unknown",
                            "image_url": relative_img_url,
                            "timestamp": current_chk.isoformat()
                        })
                        return
            finally:
                db_check.close()

            prov_plate = f"UNREADABLE-{timestamp_str[-6:]}"
            plate = prov_plate
            color = ai_results.get("color", "Unknown")
            brand = ai_results.get("brand", "Unknown")
            print(f"[AI Review] 🚗 Unidentified vehicle entered gate. Created '{plate}' ({color}, {brand}). Manual review available.")
        else:
            detail_msg = ai_results.get("message", "No vehicle or plate detected in gate area")
            if ai_results.get("plate") == "UNKNOWN":
                detail_msg = "Unreadable license plate or pedestrian motion. Visit not recorded."

            await manager.broadcast({
                "event_type": "SCAN_FAIL",
                "scan_id": scan_id,
                "detail": detail_msg
            })
            return
    else:
        plate = normalize_plate_number(ai_results["plate"])
        color = ai_results["color"]
        brand = ai_results["brand"]

    # Since this task runs after the request returns, we must open a separate DB session
    from database import SessionLocal, Vehicle, Visit
    db = SessionLocal()
    try:
        # Create or Fetch Vehicle with Fleet Registry Master Lookup
        vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate).first()
        if not vehicle:
            vehicle = Vehicle(
                plate_number=plate,
                color=color,
                brand=brand
            )
            db.add(vehicle)
            db.flush()
        else:
            # Fleet Registry Lookup: Master database record takes priority over vision estimates
            if vehicle.brand and vehicle.brand != "Unknown":
                brand = vehicle.brand
            elif brand and brand != "Unknown":
                vehicle.brand = brand

            if vehicle.color and vehicle.color != "Unknown":
                color = vehicle.color
            elif color and color != "Unknown":
                vehicle.color = color

        current_time = datetime.now()
        visit = None

        # Helper to check if a newly recognized plate (e.g. 'B 7238') upgrades a recent burst visit
        # created within the last 45s (either 'UNREADABLE-*' or a partial digit-only read like '7238').
        if not plate.startswith("UNREADABLE-") and not plate.startswith("CAR-"):
            recent_inside = db.query(Visit).filter(
                Visit.zone == zone,
                Visit.status == "Inside"
            ).order_by(Visit.id.desc()).all()
            plate_digits = re.sub(r'\D', '', plate)
            for r_vis in recent_inside:
                if not r_vis.entry_timestamp:
                    continue
                age_sec = (current_time - r_vis.entry_timestamp).total_seconds()
                if age_sec > 45.0:
                    continue
                r_plate = r_vis.plate_number or ""
                r_digits = re.sub(r'\D', '', r_plate)
                is_unreadable = r_plate.startswith("UNREADABLE-") or r_plate.startswith("CAR-")
                is_partial_upgrade = (
                    " " in plate and " " not in r_plate and not is_unreadable
                    and r_digits and plate_digits == r_digits
                )
                if is_unreadable or is_partial_upgrade or (r_plate == plate and age_sec < 25.0):
                    print(f"[AI Burst Upgrade] Consolidating recent burst visit '{r_plate}' ({age_sec:.1f}s ago) -> '{plate}'")
                    r_vis.plate_number = plate
                    r_vis.entry_image_url = relative_img_url
                    visit = r_vis
                    direction = "Entry"
                    break

        if direction == "Entry" and not visit:
            # 1. If this is an unreadable plate, check if an existing unreadable visit was created in the last 30s
            if plate.startswith("UNREADABLE-") or plate.startswith("CAR-"):
                recent_provisional = db.query(Visit).filter(
                    Visit.zone == zone,
                    Visit.status == "Inside",
                    (Visit.plate_number.like("UNREADABLE-%") | Visit.plate_number.like("CAR-%"))
                ).order_by(Visit.id.desc()).first()

                if recent_provisional:
                    time_diff = (current_time - recent_provisional.entry_timestamp).total_seconds()
                    if time_diff < 30:
                        print(f"[AI Dedup] Vehicle maneuvering in gate. Refreshing snapshot for '{recent_provisional.plate_number}'.")
                        recent_provisional.entry_image_url = relative_img_url
                        visit = recent_provisional

            # 2. Check if vehicle is already marked 'Inside' (In-facility activity suppression)
            if not visit:
                active_visit = db.query(Visit).filter(Visit.plate_number == plate, Visit.status == "Inside").first()
                if active_visit:
                    time_diff = (current_time - active_visit.entry_timestamp).total_seconds()
                    if time_diff < 60:
                        # Vehicle crossing gate hesitation: refresh snapshot
                        print(f"[AI Gatekeeper] Entry hesitation for '{plate}' ({time_diff:.1f}s). Refreshing snapshot.")
                        active_visit.entry_image_url = relative_img_url
                        visit = active_visit
                    else:
                        # Vehicle is ALREADY Inside the showroom! Staff washing/moving/inspecting is internal workshop activity.
                        print(f"[AI Gatekeeper] ℹ️ Vehicle '{plate}' is already marked 'Inside' ({time_diff:.1f}s ago). In-facility motion suppressed.")
                        db.close()
                        return
                else:
                    # Check departure debounce: If vehicle just exited within 2 minutes, do not immediately re-enter unless confirmed
                    recent_exit = db.query(Visit).filter(Visit.plate_number == plate, Visit.status == "Completed").order_by(Visit.exit_timestamp.desc()).first()
                    if recent_exit and recent_exit.exit_timestamp:
                        time_since_exit = (current_time - recent_exit.exit_timestamp).total_seconds()
                        if time_since_exit < 120:
                            print(f"[AI Gatekeeper] Vehicle '{plate}' exited only {time_since_exit:.1f}s ago. Inward hesitation/maneuver suppressed.")
                            db.close()
                            return

                    # Create new visit record
                    visit = Visit(
                        plate_number=plate,
                        zone=zone,
                        entry_timestamp=current_time,
                        entry_image_url=relative_img_url,
                        status="Inside"
                    )
                    db.add(visit)

        elif direction == "Exit" and not visit:  # Direction is "Exit"
            # Departure Debounce Guard (3-Minute Lockout):
            # Check if this vehicle ALREADY completed an exit in the last 3 minutes (180s)
            recent_completed = db.query(Visit).filter(
                Visit.plate_number == plate,
                Visit.status == "Completed"
            ).order_by(Visit.exit_timestamp.desc()).first()

            if recent_completed and recent_completed.exit_timestamp:
                time_since_exit = (current_time - recent_completed.exit_timestamp).total_seconds()
                if time_since_exit < 180:
                    print(f"[AI Lifecycle] 🚗 Vehicle '{plate}' stopped/maneuvering at exit ({time_since_exit:.1f}s after exit). Updating departure snapshot, suppressing duplicate visit.")
                    recent_completed.exit_image_url = relative_img_url
                    visit = recent_completed
                    db.commit()
                    db.refresh(visit)
                    ws_payload = {
                        "event_type": "VISIT_UPDATE",
                        "scan_id": scan_id,
                        "visit": {
                            "id": visit.id,
                            "plate_number": vehicle.plate_number,
                            "color": vehicle.color,
                            "brand": vehicle.brand,
                            "owner_name": vehicle.owner_name,
                            "owner_phone": vehicle.owner_phone,
                            "zone": visit.zone,
                            "entry_timestamp": visit.entry_timestamp.isoformat() if visit.entry_timestamp else None,
                            "exit_timestamp": visit.exit_timestamp.isoformat() if visit.exit_timestamp else None,
                            "status": visit.status,
                            "entry_image_url": visit.entry_image_url,
                            "exit_image_url": visit.exit_image_url,
                            "manually_created": visit.manually_created,
                            "manually_edited": visit.manually_edited
                        }
                    }
                    await manager.broadcast(ws_payload)
                    db.close()
                    return

            # 1. Look for exact active 'Inside' match first (must be > 25s old to avoid completing an entry burst!)
            visit = db.query(Visit).filter(Visit.plate_number == plate, Visit.status == "Inside").order_by(Visit.entry_timestamp.desc()).first()

            # 2. Fuzzy match fallback: allow minor OCR variations (e.g. 551913 vs 51913 or '7238' vs 'B 7238')
            if not visit:
                active_inside = db.query(Visit).filter(Visit.status == "Inside").all()
                best_match = None
                best_score = 0.0

                from difflib import SequenceMatcher
                plate_clean = re.sub(r'[^A-Z0-9]', '', plate.upper())
                plate_digits = re.sub(r'\D', '', plate)

                for cand in active_inside:
                    cand_clean = re.sub(r'[^A-Z0-9]', '', cand.plate_number.upper())
                    cand_digits = re.sub(r'\D', '', cand.plate_number)

                    # Check digit containment (e.g. '51913' in '551913' or '7238' in 'B 7238')
                    if cand_digits and plate_digits and len(cand_digits) >= 3 and len(plate_digits) >= 3:
                        if cand_digits in plate_digits or plate_digits in cand_digits:
                            best_match = cand
                            break

                    # Character sequence ratio
                    ratio = SequenceMatcher(None, cand_clean, plate_clean).ratio()
                    if ratio >= 0.65 and ratio > best_score:
                        best_score = ratio
                        best_match = cand

                if best_match:
                    print(f"[Matching] Fuzzy matched Exit '{plate}' to Inside visit '{best_match.plate_number}'")
                    visit = best_match

            if visit:
                visit.status = "Completed"
                visit.exit_timestamp = current_time
                visit.exit_image_url = relative_img_url
                # Ensure vehicle reflects the matched visit
                vehicle = db.query(Vehicle).filter(Vehicle.plate_number == visit.plate_number).first() or vehicle
            else:
                # Existing workshop car test mode:
                # Check if this exact plate had an exit in the last 15 minutes before creating a fresh completed visit
                prev_exit = db.query(Visit).filter(Visit.plate_number == plate, Visit.status == "Completed").order_by(Visit.exit_timestamp.desc()).first()
                if prev_exit and prev_exit.exit_timestamp and (current_time - prev_exit.exit_timestamp).total_seconds() < 900:
                    print(f"[AI Lifecycle] ℹ️ Car '{plate}' already exited previously. Suppressing duplicate exit.")
                    db.close()
                    return

                print(f"[AI Influx] Car '{plate}' arrived at gate without active visit. Recording as active Inside visit.")
                visit = Visit(
                    plate_number=plate,
                    zone=zone,
                    entry_timestamp=current_time,
                    exit_timestamp=None,
                    entry_image_url=relative_img_url,
                    exit_image_url=None,
                    status="Inside",
                    manually_created=False
                )
                db.add(visit)

        db.commit()
        db.refresh(visit)

        # Build final update payload
        ws_payload = {
            "event_type": "VISIT_UPDATE",
            "scan_id": scan_id,
            "visit": {
                "id": visit.id,
                "plate_number": vehicle.plate_number,
                "color": vehicle.color,
                "brand": vehicle.brand,
                "owner_name": vehicle.owner_name,
                "owner_phone": vehicle.owner_phone,
                "zone": visit.zone,
                "entry_timestamp": visit.entry_timestamp.isoformat() if visit.entry_timestamp else None,
                "exit_timestamp": visit.exit_timestamp.isoformat() if visit.exit_timestamp else None,
                "status": visit.status,
                "entry_image_url": visit.entry_image_url,
                "exit_image_url": visit.exit_image_url,
                "manually_created": visit.manually_created,
                "manually_edited": visit.manually_edited
            }
        }
        await manager.broadcast(ws_payload)

    except Exception as e:
        print(f"[AI Background DB] Error: {e}")
        await manager.broadcast({
            "event_type": "SCAN_FAIL",
            "scan_id": scan_id,
            "detail": f"Database processing error: {str(e)}"
        })
    finally:
        db.close()


@app.post("/api/capture")
async def capture_vehicle(
    zone: str = Form(...),         # 'Zone A' or 'Zone B'
    direction: str = Form(...),    # 'Entry' or 'Exit'
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Endpoint triggered by the Raspberry Pi.
    Saves snapshot locally, broadcasts SCAN_START immediately, 
    and offloads the AI analysis & DB write to background tasks.
    """
    if zone not in ["Zone A", "Zone B"] or direction not in ["Entry", "Exit"]:
        raise HTTPException(status_code=400, detail="Invalid zone or direction parameters")

    # 1. Save file locally
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_ext = os.path.splitext(file.filename)[1] or ".jpg"
    safe_zone_name = zone.replace(" ", "")
    filename = f"{safe_zone_name}_{direction}_{timestamp_str}{file_ext}"
    file_path = os.path.join(UPLOADS_DIR, filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    relative_img_url = f"/static/uploads/{filename}"

    # Unique Scan ID for UI linking
    scan_id = f"scan_{timestamp_str}"

    # 2. Broadcast SCAN_START instantly to frontend (to show loading skeleton card)
    await manager.broadcast({
        "event_type": "SCAN_START",
        "scan_id": scan_id,
        "zone": zone,
        "direction": direction,
        "image_url": relative_img_url,
        "timestamp": datetime.now().isoformat()
    })

    # 3. Offload AI and DB tasks to background
    if background_tasks:
        background_tasks.add_task(
            process_capture_background,
            scan_id,
            zone,
            direction,
            file_path,
            relative_img_url,
            timestamp_str
        )

    return {
        "success": True,
        "message": "Capture received, AI analysis started in background.",
        "scan_id": scan_id
    }


# --- DASHBOARD & STATISTICS ENDPOINTS ---

@app.get("/api/dashboard/stats")
def get_dashboard_statistics(db: Session = Depends(get_db)):
    """Returns today's metrics and total vehicles inside"""
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    # Total currently inside
    inside_count = db.query(func.count(Visit.id)).filter(Visit.status == "Inside").scalar() or 0
    
    # Total entries today
    entries_today = db.query(func.count(Visit.id)).filter(
        Visit.entry_timestamp >= today_start
    ).scalar() or 0

    # Total exits today
    exits_today = db.query(func.count(Visit.id)).filter(
        Visit.exit_timestamp >= today_start
    ).scalar() or 0

    # Zone stats inside now
    inside_zone_a = db.query(func.count(Visit.id)).filter(Visit.status == "Inside", Visit.zone == "Zone A").scalar() or 0
    inside_zone_b = db.query(func.count(Visit.id)).filter(Visit.status == "Inside", Visit.zone == "Zone B").scalar() or 0

    return {
        "inside_total": inside_count,
        "entries_today": entries_today,
        "exits_today": exits_today,
        "zone_a_inside": inside_zone_a,
        "zone_b_inside": inside_zone_b
    }


@app.get("/api/visits/active")
def get_active_visits(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get list of all vehicles currently inside the workshop"""
    visits = db.query(Visit).filter(Visit.status == "Inside").order_by(Visit.entry_timestamp.desc()).all()
    
    results = []
    for v in visits:
        vehicle = db.query(Vehicle).filter(Vehicle.plate_number == v.plate_number).first()
        results.append({
            "id": v.id,
            "plate_number": v.plate_number,
            "color": vehicle.color if vehicle else "Unknown",
            "brand": vehicle.brand if vehicle else "Unknown",
            "owner_name": vehicle.owner_name if vehicle else None,
            "owner_phone": vehicle.owner_phone if vehicle else None,
            "zone": v.zone,
            "entry_timestamp": v.entry_timestamp.isoformat(),
            "entry_image_url": v.entry_image_url
        })
    return results


@app.get("/api/visits/history")
def get_visits_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of past visits, including completed and active ones"""
    visits = db.query(Visit).order_by(Visit.entry_timestamp.desc()).limit(limit).all()
    
    results = []
    for v in visits:
        vehicle = db.query(Vehicle).filter(Vehicle.plate_number == v.plate_number).first()
        results.append({
            "id": v.id,
            "plate_number": v.plate_number,
            "color": vehicle.color if vehicle else "Unknown",
            "brand": vehicle.brand if vehicle else "Unknown",
            "owner_name": vehicle.owner_name if vehicle else None,
            "owner_phone": vehicle.owner_phone if vehicle else None,
            "zone": v.zone,
            "entry_timestamp": v.entry_timestamp.isoformat(),
            "exit_timestamp": v.exit_timestamp.isoformat() if v.exit_timestamp else None,
            "status": v.status,
            "entry_image_url": v.entry_image_url,
            "exit_image_url": v.exit_image_url,
            "manually_created": v.manually_created,
            "manually_edited": v.manually_edited
        })
    return results


# --- VEHICLES & OWNER INFORMATION MANAGEMENT ---

@app.put("/api/vehicles/{plate_number}")
def update_vehicle_owner_info(
    plate_number: str,
    owner_name: Optional[str] = Form(None),
    owner_phone: Optional[str] = Form(None),
    owner_email: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    brand: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add/Edit vehicle details and owner info"""
    plate_cleaned = normalize_plate_number(plate_number)
    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate_cleaned).first()
    
    if not vehicle:
        # Create a new vehicle record manually if it doesn't exist
        vehicle = Vehicle(plate_number=plate_cleaned)
        db.add(vehicle)
        
    if owner_name is not None:
        vehicle.owner_name = owner_name
    if owner_phone is not None:
        vehicle.owner_phone = owner_phone
    if owner_email is not None:
        vehicle.owner_email = owner_email
    if color is not None:
        vehicle.color = color
    if brand is not None:
        vehicle.brand = brand
        
    db.commit()
    db.refresh(vehicle)
    return {
        "success": True,
        "plate_number": vehicle.plate_number,
        "color": vehicle.color,
        "brand": vehicle.brand,
        "owner_name": vehicle.owner_name,
        "owner_phone": vehicle.owner_phone,
        "owner_email": vehicle.owner_email
    }


# --- MANUAL VISIT ENTRIES & EDITS ---

@app.post("/api/visits/manual")
def create_manual_visit(
    plate_number: str = Form(...),
    zone: str = Form(...),
    direction: str = Form(...), # 'Entry' or 'Exit'
    timestamp: str = Form(...), # ISO Format string
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Allows manual override injection of vehicle visits"""
    if zone not in ["Zone A", "Zone B"] or direction not in ["Entry", "Exit"]:
        raise HTTPException(status_code=400, detail="Invalid parameters")
        
    plate_cleaned = normalize_plate_number(plate_number)
    
    # Verify vehicle exists, if not auto create
    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate_cleaned).first()
    if not vehicle:
        vehicle = Vehicle(plate_number=plate_cleaned, color="Unknown", brand="Unknown")
        db.add(vehicle)
        db.flush()

    try:
        parsed_time = datetime.fromisoformat(timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO timestamp format")

    if direction == "Entry":
        # Check if there is already an active visit inside
        active_visit = db.query(Visit).filter(Visit.plate_number == plate_cleaned, Visit.status == "Inside").first()
        if active_visit:
            raise HTTPException(status_code=400, detail="This vehicle is already logged as inside the workshop.")

        visit = Visit(
            plate_number=plate_cleaned,
            zone=zone,
            entry_timestamp=parsed_time,
            status="Inside",
            manually_created=True
        )
        db.add(visit)
    else:
        # Direction is Exit
        active_visit = db.query(Visit).filter(Visit.plate_number == plate_cleaned, Visit.status == "Inside").order_by(Visit.entry_timestamp.desc()).first()
        if active_visit:
            active_visit.status = "Completed"
            active_visit.exit_timestamp = parsed_time
            active_visit.manually_edited = True
            visit = active_visit
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Vehicle '{plate_cleaned}' is not currently logged as inside the workshop. Cannot log exit."
            )
            
    db.commit()
    db.refresh(visit)
    return {"success": True, "visit_id": visit.id}


@app.put("/api/visits/{visit_id}")
def edit_visit_record(
    visit_id: int,
    plate_number: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    brand: Optional[str] = Form(None),
    zone: Optional[str] = Form(None),
    entry_timestamp: Optional[str] = Form(None),
    exit_timestamp: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Allows manual editing of an existing visit log (e.g. if AI misread plate number or brand/color)"""
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit record not found")
        
    visit.manually_edited = True
    
    target_plate = visit.plate_number
    if plate_number is not None:
        plate_cleaned = normalize_plate_number(plate_number)
        # Ensure vehicle exists
        vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate_cleaned).first()
        if not vehicle:
            old_veh = db.query(Vehicle).filter(Vehicle.plate_number == visit.plate_number).first()
            inh_col = old_veh.color if old_veh else "Unknown"
            inh_brd = old_veh.brand if old_veh else "Unknown"
            vehicle = Vehicle(plate_number=plate_cleaned, color=inh_col, brand=inh_brd)
            db.add(vehicle)
            db.flush()
        visit.plate_number = plate_cleaned
        target_plate = plate_cleaned

    # Update vehicle master record brand and color if provided
    vehicle_rec = db.query(Vehicle).filter(Vehicle.plate_number == target_plate).first()
    if vehicle_rec:
        if color is not None and color.strip():
            vehicle_rec.color = color.strip()
        if brand is not None and brand.strip():
            vehicle_rec.brand = brand.strip()
        
    if zone is not None:
        if zone not in ["Zone A", "Zone B"]:
            raise HTTPException(status_code=400, detail="Invalid zone")
        visit.zone = zone
        
    if entry_timestamp is not None:
        try:
            visit.entry_timestamp = datetime.fromisoformat(entry_timestamp)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid entry ISO timestamp format")
            
    if exit_timestamp is not None:
        if exit_timestamp == "":
            visit.exit_timestamp = None
        else:
            try:
                visit.exit_timestamp = datetime.fromisoformat(exit_timestamp)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid exit ISO timestamp format")
            
    if status is not None:
        if status not in ["Inside", "Completed"]:
            raise HTTPException(status_code=400, detail="Invalid status")
        visit.status = status
        
    db.commit()
    return {"success": True, "visit_id": visit.id}


class ConfirmExitRequest(BaseModel):
    visit_id: int
    exit_image_url: Optional[str] = None


@app.post("/api/visits/confirm-unverified-exit")
async def confirm_unverified_exit(
    req: ConfirmExitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Allows 1-click confirmation of an unverified exit (e.g. car exiting in reverse with unreadable plate)"""
    visit = db.query(Visit).filter(Visit.id == req.visit_id, Visit.status == "Inside").first()
    if not visit:
        raise HTTPException(
            status_code=404,
            detail="Visit not found or vehicle is not currently logged as Inside"
        )

    visit.status = "Completed"
    visit.exit_timestamp = datetime.now()
    if req.exit_image_url:
        visit.exit_image_url = req.exit_image_url
    visit.manually_edited = True

    db.commit()
    db.refresh(visit)

    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == visit.plate_number).first()

    # Broadcast update live to all connected dashboards
    await manager.broadcast({
        "event_type": "VISIT_UPDATE",
        "visit": {
            "id": visit.id,
            "plate_number": visit.plate_number,
            "color": vehicle.color if vehicle else "Unknown",
            "brand": vehicle.brand if vehicle else "Unknown",
            "owner_name": vehicle.owner_name if vehicle else None,
            "owner_phone": vehicle.owner_phone if vehicle else None,
            "zone": visit.zone,
            "entry_timestamp": visit.entry_timestamp.isoformat() if visit.entry_timestamp else None,
            "exit_timestamp": visit.exit_timestamp.isoformat() if visit.exit_timestamp else None,
            "status": visit.status,
            "entry_image_url": visit.entry_image_url,
            "exit_image_url": visit.exit_image_url,
            "manually_created": visit.manually_created,
            "manually_edited": visit.manually_edited
        }
    })
    return {"success": True, "visit_id": visit.id}


# --- STORAGE & MAINTENANCE ENDPOINTS ---

@app.get("/api/maintenance/storage-stats")
def storage_stats_endpoint(current_user: User = Depends(get_current_user)):
    """Returns current image storage statistics and files eligible for deletion"""
    from maintenance import get_storage_stats
    return get_storage_stats()


@app.post("/api/maintenance/cleanup-images")
def cleanup_images_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Manually triggers cleanup of images older than the retention period"""
    from maintenance import cleanup_old_images
    result = cleanup_old_images(db)
    return result
