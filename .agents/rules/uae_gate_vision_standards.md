# UAE Gate Vision & Tracking Standards

## 1. UAE License Plate Normalization
- **Abu Dhabi plates format**: `[Category] [Number]` (e.g. `10 55456`). Always cluster bounding boxes horizontally before OCR parsing to overcome CRAFT segmenter splits on the category badge.
- **Dubai plates format**: `[Code] [Number]` (e.g. `M 11770`, `AA 1234`).
- **Left-Prefix Expansion**: If a plain numeric string is extracted, check left-expanded bumper crop for a category badge or emirate code.
- **Digit Disambiguation**: Disambiguate common OCR letter/digit confusions in numeric zones (e.g., 'O'/'Q'/'D' -> '0', 'I'/'l'/'|' -> '1', 'S' -> '5', 'B' -> '8').

## 2. Vehicle Brand & Sub-Brand Resolution
- **Grille Crop**: Target the upper-center grille region above the front license plate.
- **Fuzzy Matching**: Apply fuzzy string matching (`SequenceMatcher` threshold >= 0.65) to handle chrome glare and specular reflections (e.g. `VissaN` -> `Nissan`).
- **Sub-Brand Aliases**: Map performance lines to parent marques (`NISMO` -> `Nissan`, `AMG` -> `Mercedes-Benz`, `M` -> `BMW`).
- **Master Fleet Memory**: Once a vehicle's make and model are confirmed, save to the master fleet database so subsequent visits auto-populate permanently.

## 3. Direction & Depth Tracking (Single Camera)
- **Centroid Tracking**: Track vehicle geometric centroid `C(x, y)` to avoid bounding-box overlap ambiguity on large vehicles (SUVs).
- **Perspective Scale Factor**:
  - Top -> Down with Area Growth Ratio >= 1.05 = **ENTRY**.
  - Down -> Top with Area Shrink Ratio <= 0.95 = **EXIT**.
- **Cross-Traffic Suppression**: Filter out horizontal public street traffic (|dx| > 1.3 * |dy|).
- **Origin Guard**: Entry must strictly originate at top ramp (y <= y_top + 25px); Exit must start at bay floor (y >= y_bottom - 25px). Motion originating inside the room is discarded as internal motion.

## 4. Corridor Gatekeeping in Mixed Glass/Outdoor Showrooms
- **Stationary Background Rejection**: Distant parked vehicles outside (y2 < 330px) must never trigger active visits.
- **Sideline Filter**: Sideline vehicles outside the driveway lane (x1 > 1100px or x2 < 120px) are ignored.
- **Strict Unreadable Threshold**: Unreadable visit fallback requires a massive vehicle physically occupying the entryway (bw >= 300, bh >= 200, area >= 50,000).
- **Pedestrian Rejection**: Reject human and pedestrian motion in doorway without logging false visits.
