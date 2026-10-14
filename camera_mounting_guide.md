# 📷 Camera Mounting & Alignment Guide

Use this together with the **Camera Settings** page of the dashboard
(live view at `http://192.168.0.240:8080/stream.mjpg`). The red/green lines are
drawn by the Pi from the values in `edge/edge_tracker.py`.

---

## 1. Physical placement

| Parameter | Recommended | Why |
| :--- | :--- | :--- |
| Height | 1.2 – 2.0 m (chest to head level) | Keeps plates readable and avoids roof-only views |
| Distance to the car path | 5 – 15 m | Closer = better OCR; beyond ~15 m plates become unreadable |
| Horizontal angle to lane | ≤ 30° off the lane axis | Steeper angles skew plates and break OCR |
| Vertical tilt | 0 – 10° down | Horizon level, no sky-dominated frame |
| Lens | Clean, behind clean glass | Glass adds reflections; keep the lens close to it |

```
 Good (top view)                          Bad (top view)

   street lane  ───────▶ car                street lane  ───────▶ car
                    ╲                                     │
                     ╲ ≤30°                               │ 90° side-on
                  [CAM]                                [CAM]  (plate unreadable)
```

```
 Good (side view)                         Bad (side view)

        [CAM] 1.5 m  ╲                       [CAM] 4 m, tilted far down
          │            ╲ 5° down                │ ╲
 ─────────┴──────────── car plate in            │  ╲ roofs only, no plates
          lower third of frame
```

## 2. Frame composition (what you should see)

1. **Horizon level.** Enable *Level guide* in Camera Settings.
2. **Lane crosses both tripwires.** The car must pass the red line
   (`TRIPWIRE_TOP_Y = 0.36`) and the green line (`TRIPWIRE_BOTTOM_Y = 0.58`).
3. **Plate in the lower third** when the car reaches the green line. Use *Rule of thirds*.
4. **Indoor floor stays below the grey mask** (`DETECTION_Y_MAX = 0.64`),
   so staff walking inside are ignored.
5. No pillars, signs or doors cutting the lane (the pillar on the left of your
   current view is fine; keep it out of the lane).

### Example – your current view
- ✅ Both tripwires sit over the outside street/ramp.
- ✅ Indoor floor is masked out.
- ⚠️ Glass reflections (ceiling lights) are strong. Move the lens within 5 cm of
  the glass or add a lens hood / black cloth around the lens.
- ⚠️ Status bar showed `????`. Fixed in `edge_tracker.py`; restart the Pi script.

## 3. Direction logic (Entry vs Exit)

| Order of Crossing / Vector | Driveway Threshold Requirement | Resulting API Event |
| :--- | :--- | :--- |
| **Red Top → Green Bottom** | Crosses down ramp into showroom threshold (`y >= y_bottom`) | **`Entry`** (`POST /api/capture`, `zone: "Zone A"`, `direction: "Entry"`) → Status **Inside** |
| **Green Bottom → Red Top** | Starts at showroom threshold (`y >= y_bottom`) & moves up ramp | **`Exit`** (`POST /api/capture`, `zone: "Zone A"`, `direction: "Exit"`) → Status **Completed** |
| **Horizontal Street Movement** | Does NOT reach or cross green threshold line | **IGNORED** (Pass-through street traffic; no false triggers) |

### Key Principles for Single-Camera In/Out:
1. **Red Line (`TRIPWIRE_TOP_Y = 0.36`)**: Positioned at the distant outside street/ramp edge.
2. **Green Line (`TRIPWIRE_BOTTOM_Y = 0.58`)**: Positioned at the showroom entrance threshold.
3. **Threshold Gate Requirement**: Both Entry and Exit require intersecting the green showroom threshold. Pure horizontal street movement (cars passing left/right in the background) is filtered out.
4. **Orientation Invariant**: Whether a car enters forward (front plate) or in reverse (rear plate), or exits forward or backward, the physical motion vector (Street ↔ Showroom) correctly registers the movement.

## 4. Tuning examples (edit `edge_tracker.py`, then restart)

| Situation | Change |
| :--- | :--- |
| Cars are triggered too late | `TRIPWIRE_TOP_Y = 0.30` (move red line up) |
| Plates cut off at the bottom | `TRIPWIRE_BOTTOM_Y = 0.50` |
| Pedestrians trigger captures | Lower `DETECTION_Y_MAX` (e.g. `0.60`), raise `MIN_VEHICLE_WIDTH` to `90` |
| Small/distant cars missed | `MIN_CONTOUR_AREA = 2400`, `MIN_VEHICLE_WIDTH = 60` |
| Same car captured twice | Raise `CAPTURE_COOLDOWN` to `20` |
| Night headlight glare | Angle camera 10–15° off the lane, avoid facing lights |

## 5. Step-by-step mounting checklist

1. Fix the camera temporarily (tape/clamp) at ~1.5 m, 5–15 m from the lane.
2. Open dashboard → **Camera Settings** → *Gate Camera* → **Apply & Reconnect**.
3. Turn on *Center crosshair*, *Rule of thirds*, *Level guide*.
4. Walk/drive a car past: it must cross red then green fully inside the frame.
5. Click **Snapshot** with a car at the green line; check the plate is sharp and readable.
6. Tighten mount, re-check live view hasn't shifted.
7. Re-check at night and in direct sun; adjust angle if glare appears.
8. Run a full test (section 6).

## 6. Full-system test (Pi → laptop)

```powershell
# Laptop: start backend (listens on all adapters)
cd backend
venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000

# Laptop: pull a live frame from the Pi
venv\Scripts\python fetch_live.py

# Laptop: push it through the AI pipeline
curl.exe -F "zone=Zone A" -F "direction=Entry" -F "file=@uploads/live_preview.jpg" http://127.0.0.1:8000/api/capture
```

On the Pi:
```bash
python3 edge_tracker.py   # API_URL must be http://192.168.0.24:8000/api/capture
```

Expected: a scanning card appears on the dashboard, then updates with plate, colour and brand.
