import os
import re
import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO
import easyocr
from difflib import SequenceMatcher

import threading

# Initialize global models
yolo_model = None
ocr_reader = None
_init_lock = threading.Lock()

# Words to ignore from on-screen graphics or signage
IGNORED_WORDS = {
    "STATUS", "STATU", "READY", "WAITING", "TRIPWIRE", "BOTTOM", "TOP",
    "INSIDE", "OUTSIDE", "CLOSE", "DISTANT", "DUBAI", "UAE", "ABUDHABI",
    "FORWARD", "DEPARTURE", "CHECKIN", "CHECKOUT", "ZONEA", "ZONEB"
}

def init_models():
    """Thread-safe initialization of AI models"""
    global yolo_model, ocr_reader
    with _init_lock:
        if yolo_model is None:
            print("[AI] Loading YOLOv8 nano detector...")
            yolo_model = YOLO("yolov8n.pt")
            
        if ocr_reader is None:
            print("[AI] Loading EasyOCR reader...")
            ocr_reader = easyocr.Reader(['en'], gpu=False)


NUMERIC_TRANSLATION = str.maketrans({
    'O': '0', 'o': '0', 'Q': '0', 'D': '0',
    'I': '1', 'i': '1', 'l': '1', '|': '1', '!': '1',
    'Z': '2', 'z': '2',
    'S': '5', 's': '5',
    'G': '6', 'b': '6',
    'B': '8',
})

def disambiguate_digits(text: str) -> str:
    """Translates common OCR letter confusions in numeric plate sections into digits."""
    return text.translate(NUMERIC_TRANSLATION)


def clean_plate_candidate(raw_text: str):
    """
    Cleans raw OCR text into standard UAE license plate formats:
    - Abu Dhabi: [Category] [Digits] e.g. '10 55456', '4 12345', '50 9999'
    - Dubai: [Letter(s)] [Digits] e.g. 'M 11770', 'AA 1234', 'C 90371'
    - Plain Digits: 3 to 6 digits (e.g. '55456', '24384')
    """
    cleaned = re.sub(r'[^A-Z0-9\s]', '', raw_text.upper()).strip()
    words = [w for w in cleaned.split() if w not in IGNORED_WORDS and len(w) >= 1]
    cleaned = " ".join(words)

    # 1. Abu Dhabi Category Format: Category prefix (1-50) + 3-6 digits
    match_ad = re.search(r'\b(1|2|3|4|5|6|7|8|9|10|11|12|14|15|16|17|50)\s+([0-9OIl!SBZG]{3,6})\b', cleaned)
    if match_ad:
        cat = match_ad.group(1)
        digits = disambiguate_digits(match_ad.group(2))
        if digits.isdigit() and 3 <= len(digits) <= 6:
            return f"{cat} {digits}", len(digits) + 3

    # 2. Dubai Format: 1 or 2 letter code + 1 to 5 digits (e.g. 'M 11770', 'AA 1234')
    match_dubai = re.search(r'\b([A-Z]{1,2})\s*([0-9OIl!SBZG]{1,5})\b', cleaned)
    if match_dubai:
        letter_code = match_dubai.group(1)
        raw_num = match_dubai.group(2)
        digits = disambiguate_digits(raw_num)
        if digits.isdigit() and 1 <= len(digits) <= 5:
            return f"{letter_code} {digits}", len(digits) + 3

    # 3. Plain Numeric Plates: 3 to 6 digits (e.g. '51913', '24384', '55456')
    tokens = cleaned.split()
    for tok in tokens:
        if 3 <= len(tok) <= 6:
            converted = disambiguate_digits(tok)
            if converted.isdigit() and sum(c.isdigit() for c in tok) >= 2:
                return converted, len(converted)

    # 4. General Alphanumeric Fallback (3 to 8 characters with at least 3 digits)
    compact = re.sub(r'\s+', '', cleaned)
    if 3 <= len(compact) <= 8:
        m = re.match(r'^([A-Z]{1,2})([0-9OIl!SBZG]{3,5})$', compact)
        if m:
            code = m.group(1)
            digits = disambiguate_digits(m.group(2))
            if digits.isdigit():
                return f"{code} {digits}", len(digits) + 3
        
        digit_count = sum(c.isdigit() for c in compact)
        if digit_count >= 3:
            return compact, len(compact)

    return None, 0


def extract_license_plate(vehicle_img) -> str:
    """
    Multi-pass OCR reader with UAE spatial horizontal clustering and category expansion:
    1. Samples lower bumper where license plates reside.
    2. Runs multi-pass filters (Upscaled CLAHE, Bilateral Glare Reduction, Otsu).
    3. Clusters horizontally-adjacent boxes (e.g. ['10', '55456'] -> '10 55456').
    4. If a plain numeric plate is found, expands to the left to catch category box.
    """
    init_models()
    if vehicle_img is None or vehicle_img.size == 0:
        return "UNKNOWN"

    candidates = []
    vh, vw = vehicle_img.shape[:2]

    # Sample lower bumper area (where plates are mounted)
    bumper_crop = vehicle_img[int(vh * 0.25):vh, :] if vh >= 40 else vehicle_img
    
    gray = cv2.cvtColor(bumper_crop, cv2.COLOR_BGR2GRAY)
    bumper_up = cv2.resize(bumper_crop, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    
    passes = [
        ("bumper_up", bumper_up),
        ("clahe", cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8)).apply(cv2.resize(gray, (0, 0), fx=2.0, fy=2.0))),
        ("bilateral", cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8)).apply(cv2.bilateralFilter(cv2.resize(gray, (0, 0), fx=2.0, fy=2.0), 9, 75, 75))),
    ]
    
    for pass_name, proc_img in passes:
        ocr_res = ocr_reader.readtext(proc_img)
        if not ocr_res:
            continue
            
        scale_x = proc_img.shape[1] / bumper_crop.shape[1]
        scale_y = proc_img.shape[0] / bumper_crop.shape[0]

        boxes = []
        for bbox, text, conf in ocr_res:
            if not text.strip() or conf < 0.15:
                continue
            bx1 = bbox[0][0] / scale_x
            by1 = bbox[0][1] / scale_y
            bx2 = bbox[1][0] / scale_x
            by2 = bbox[2][1] / scale_y
            cx = (bx1 + bx2) / 2.0
            cy = (by1 + by2) / 2.0
            h = abs(by2 - by1)
            w = abs(bx2 - bx1)
            boxes.append({'text': text.strip(), 'cx': cx, 'cy': cy, 'h': h, 'w': w, 'box': [bx1, by1, bx2, by2], 'conf': conf})

        # Horizontal clustering (group boxes with similar Y on the same horizontal line)
        clusters = []
        for b in sorted(boxes, key=lambda x: x['cx']):
            merged = False
            for cl in clusters:
                avg_cy = sum(item['cy'] for item in cl) / len(cl)
                avg_h = sum(item['h'] for item in cl) / len(cl)
                if abs(b['cy'] - avg_cy) < max(avg_h, b['h']) * 0.8:
                    cl.append(b)
                    merged = True
                    break
            if not merged:
                clusters.append([b])

        # Evaluate clustered lines
        for cl in clusters:
            cl.sort(key=lambda x: x['cx'])
            joined_str = " ".join(item['text'] for item in cl)
            plate_str, bonus = clean_plate_candidate(joined_str)
            if plate_str:
                conf_avg = sum(item['conf'] for item in cl) / len(cl)
                candidates.append((plate_str, conf_avg + bonus, cl))

        # Also evaluate individual boxes
        for b in boxes:
            plate_str, bonus = clean_plate_candidate(b['text'])
            if plate_str:
                candidates.append((plate_str, b['conf'] + bonus, [b]))

    # Prefix expansion check:
    # If best candidate is a plain numeric plate (e.g. '55456' without category),
    # expand the crop to the left in the bumper to catch the Abu Dhabi / Dubai category prefix!
    final_candidates = []
    for plate_str, score, cl in candidates:
        if " " not in plate_str and plate_str.isdigit():
            min_x = min(item['box'][0] for item in cl)
            max_x = max(item['box'][2] for item in cl)
            min_y = min(item['box'][1] for item in cl)
            max_y = max(item['box'][3] for item in cl)
            bw = max_x - min_x
            bh = max_y - min_y

            ex_x1 = max(0, int(min_x - bw * 1.3))
            ex_x2 = min(bumper_crop.shape[1], int(max_x + bw * 0.2))
            ex_y1 = max(0, int(min_y - bh * 0.3))
            ex_y2 = min(bumper_crop.shape[0], int(max_y + bh * 0.3))

            expanded_sub = bumper_crop[ex_y1:ex_y2, ex_x1:ex_x2]
            if expanded_sub.size > 0:
                sub_res = ocr_reader.readtext(expanded_sub)
                sub_items = []
                for s_bbox, s_text, s_conf in sub_res:
                    s_cx = (s_bbox[0][0] + s_bbox[1][0]) / 2.0
                    sub_items.append((s_cx, s_text, s_conf))
                sub_items.sort(key=lambda x: x[0])
                expanded_joined = " ".join(x[1] for x in sub_items)
                exp_plate, exp_bonus = clean_plate_candidate(expanded_joined)
                if exp_plate and " " in exp_plate:
                    final_candidates.append((exp_plate, score + 3.0))
                    continue
        final_candidates.append((plate_str, score))

    if final_candidates:
        final_candidates.sort(key=lambda x: x[1], reverse=True)
        return final_candidates[0][0]

    return "UNKNOWN"



KNOWN_BRANDS = [
    "PORSCHE", "MERCEDES-BENZ", "MERCEDES", "BMW", "AUDI", "LEXUS", 
    "TOYOTA", "NISSAN", "LAND ROVER", "RANGE ROVER", "FERRARI", 
    "LAMBORGHINI", "BENTLEY", "ROLLS ROYCE", "ASTON MARTIN", "MCLAREN",
    "JEEP", "FORD", "CHEVROLET", "CADILLAC", "GMC", "HYUNDAI", "KIA", 
    "TESLA", "VOLKSWAGEN", "MITSUBISHI", "HONDA", "MAZDA", "SUBARU", 
    "SUZUKI", "INFINITI", "JAGUAR", "DODGE", "RAM", "MASERATI", 
    "GENESIS", "BYD", "GEELY", "MG", "HAVAL", "CHERY", "JETOUR"
]

def classify_color(vehicle_img) -> str:
    """
    Paint-focused automotive color classification.
    Samples the middle body panel (25%-75% height, 15%-85% width) to avoid
    the dark windshield/roof tint above and the black tires/asphalt below.
    Classifies into the Standard Automotive Palette:
    White, Black, Silver/Grey, Blue, Red, Brown/Gold, Green, Yellow
    """
    if vehicle_img is None or vehicle_img.size == 0:
        return "Unknown"

    vh, vw = vehicle_img.shape[:2]
    # Sample middle body paint
    y_start, y_end = int(vh * 0.25), int(vh * 0.75)
    x_start, x_end = int(vw * 0.15), int(vw * 0.85)

    if y_end <= y_start or x_end <= x_start:
        body_crop = vehicle_img
    else:
        body_crop = vehicle_img[y_start:y_end, x_start:x_end]

    img_resized = cv2.resize(body_crop, (100, 100))
    hsv = cv2.cvtColor(img_resized, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3)

    color_counts = {
        "White": 0, "Black": 0, "Silver/Grey": 0,
        "Red": 0, "Blue": 0, "Brown/Gold": 0,
        "Green": 0, "Yellow": 0
    }

    for h_val, s, v in pixels:
        # Exclude extreme specular glare and pitch-black underbody shadow crevices
        if v < 30 or (v > 245 and s < 15):
            continue

        if s < 45:  # Low saturation: Black / Silver/Grey / White
            if v > 165:
                color_counts["White"] += 1
            elif v < 65:
                color_counts["Black"] += 1
            else:
                color_counts["Silver/Grey"] += 1
        else:  # Saturated colors
            if (0 <= h_val < 10) or (160 <= h_val <= 180):
                color_counts["Red"] += 1
            elif 10 <= h_val < 22:
                if v < 110:
                    color_counts["Brown/Gold"] += 1
                else:
                    color_counts["Yellow"] += 1
            elif 22 <= h_val < 38:
                if v < 110:
                    color_counts["Brown/Gold"] += 1
                else:
                    color_counts["Yellow"] += 1
            elif 38 <= h_val < 85:
                color_counts["Green"] += 1
            elif 85 <= h_val < 135:
                color_counts["Blue"] += 1
            elif 135 <= h_val < 160:
                color_counts["Red"] += 1

    sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
    if sorted_colors and sorted_colors[0][1] > 0:
        return sorted_colors[0][0]
    return "Unknown"


def classify_brand(vehicle_img, raw_text_tokens=None) -> str:
    """
    Classifies vehicle brand:
    1. Checks raw OCR tokens if provided.
    2. Scans the front grille / rear badge area (upper 45% height, center 25%-75% width).
    3. Runs EasyOCR on 2x upscaled badge crop.
    4. Performs fuzzy matching (SequenceMatcher) against KNOWN_BRANDS.
    5. Recognizes performance sub-brands (e.g. NISMO -> Nissan, AMG -> Mercedes-Benz, M -> BMW).
    """
    init_models()
    if vehicle_img is None or vehicle_img.size == 0:
        return "Unknown"

    vh, vw = vehicle_img.shape[:2]
    # Sample upper center grille / badge region
    grille_crop = vehicle_img[0:int(vh * 0.45), int(vw * 0.25):int(vw * 0.75)]
    if grille_crop.shape[0] >= 20 and grille_crop.shape[1] >= 30:
        grille_up = cv2.resize(grille_crop, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        res = ocr_reader.readtext(grille_up)

        best_brand = "Unknown"
        best_sim = 0.0

        for bbox, text, conf in res:
            clean_t = re.sub(r'[^A-Z]', '', text.upper())
            if not clean_t:
                continue

            # Special sub-brand mappings
            if "NISMO" in clean_t:
                return "Nissan"
            if "AMG" in clean_t:
                return "Mercedes-Benz"

            for brand in KNOWN_BRANDS:
                brand_clean = re.sub(r'[^A-Z]', '', brand)
                sim = SequenceMatcher(None, clean_t, brand_clean).ratio()
                if clean_t in brand_clean and len(clean_t) >= 4:
                    sim = 1.0
                if brand_clean in clean_t:
                    sim = 1.0

                if sim > 0.65 and sim > best_sim:
                    best_sim = sim
                    best_brand = brand.title()

        if best_brand != "Unknown":
            return best_brand

    return "Unknown"



def run_ai_pipeline(image_path: str):
    """
    Strict Vehicle AI Pipeline:
    1. Detect candidate vehicles using YOLOv8 with strict qualification:
       - Confidence >= 0.35
       - Bounding box >= 120x100 px
       - Strictly Vehicle classes: car (2), motorcycle (3), bus (5), truck (7)
       - Strictly ignores pedestrians, bicycles, animals, bags, skateboards, and reflections.
    2. Runs multi-pass OCR on candidate vehicle crops.
    3. If valid plate found: classifies body paint color and checks emblem text.
    4. If vehicle verified in gate but plate obscured: returns vehicle_detected=True with plate='UNKNOWN'.
    """
    init_models()
    img = cv2.imread(image_path)
    if img is None:
        return {
            "success": False,
            "vehicle_detected": False,
            "plate": "UNKNOWN",
            "color": "Unknown",
            "brand": "Unknown",
            "coords": [0, 0, 0, 0],
            "message": "Failed to read image"
        }

    results = yolo_model(img, verbose=False, conf=0.25)
    h, w, _ = img.shape

    candidate_vehicles = []
    has_foreground_person = False
    person_box = None

    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            bw = x2 - x1
            bh = y2 - y1
            area = bw * bh

            # Check for person in doorway or foreground
            if cls_id == 0 and y2 > 250:
                has_foreground_person = True
                person_box = [x1, y1, x2, y2]

            # Vehicle Classes: car (2), motorcycle (3), bus (5), truck (7)
            if cls_id in [2, 3, 5, 7] and conf >= 0.35:
                # Active Gate Corridor Gatekeeper:
                # 1. Distant Parked Vehicle Filter:
                #    A vehicle entering/exiting the gate MUST reach the entryway threshold (y2 >= 330).
                #    Vehicles strictly above y2 < 330 are parked outside on the street/ramp and must be ignored.
                if y2 < 330:
                    continue

                # 2. Sideline Filter:
                #    Ignore parked vehicles on far sides outside the driveway (x1 > 1100 or x2 < 120)
                if x1 > 1100 or x2 < 120:
                    continue

                # 3. Minimum vehicle dimensions in entryway
                if bw >= 220 and bh >= 140:
                    score = conf * (area ** 0.5)
                    candidate_vehicles.append((score, area, bw, bh, [x1, y1, x2, y2]))

    # If NO vehicle is in the active gate corridor, ignore the capture entirely
    if not candidate_vehicles:
        if has_foreground_person:
            print("[AI] 🚶 Pedestrian / staff motion detected at gate. Ignored.")
            return {
                "success": False,
                "vehicle_detected": False,
                "plate": "UNKNOWN",
                "color": "Unknown",
                "brand": "Unknown",
                "coords": [0, 0, 0, 0],
                "message": "Pedestrian motion at gate (ignored)"
            }
        print("[AI] ℹ️ Background parked vehicles or non-vehicle motion ignored (no vehicle in active gate corridor).")
        return {
            "success": False,
            "vehicle_detected": False,
            "plate": "UNKNOWN",
            "color": "Unknown",
            "brand": "Unknown",
            "coords": [0, 0, 0, 0],
            "message": "No valid vehicle in active gate corridor (ignored)"
        }

    # Sort candidate vehicles by score (size and confidence)
    candidate_vehicles.sort(key=lambda x: x[0], reverse=True)

    best_plate = "UNKNOWN"
    selected_crop = None
    selected_box = None
    detected_tokens = []

    # Test OCR across qualified candidate vehicles in gate
    for score, area, bw, bh, box in candidate_vehicles:
        x1, y1, x2, y2 = box
        # Add 5% padding around crop
        pad_x = int((x2 - x1) * 0.05)
        pad_y = int((y2 - y1) * 0.05)
        cx1 = max(0, x1 - pad_x)
        cy1 = max(0, y1 - pad_y)
        cx2 = min(w, x2 + pad_x)
        cy2 = min(h, y2 + pad_y)

        crop = img[cy1:cy2, cx1:cx2]
        plate = extract_license_plate(crop)
        if plate != "UNKNOWN":
            best_plate = plate
            selected_crop = crop
            selected_box = [cx1, cy1, cx2, cy2]
            break

    # If a valid plate was found on any candidate vehicle, we have our match!
    if best_plate != "UNKNOWN" and selected_crop is not None:
        color = classify_color(selected_crop)
        brand = classify_brand(selected_crop, detected_tokens)
        print(f"[AI] ✅ Vehicle recognized! Plate: {best_plate}, Color: {color}, Brand: {brand}")
        return {
            "success": True,
            "vehicle_detected": True,
            "plate": best_plate,
            "color": color,
            "brand": brand,
            "coords": [int(c) for c in selected_box],
            "quality_score": 100.0 + (25.0 if brand != "Unknown" else 0.0) + (10.0 if color != "Unknown" else 0.0)
        }

    # If no readable plate, only allow UNREADABLE visit if a massive vehicle physically occupies the entryway
    top_score, top_area, top_bw, top_bh, top_box = candidate_vehicles[0]
    person_blocking_car = False
    if has_foreground_person and person_box:
        px1, py1, px2, py2 = person_box
        cx1, cy1, cx2, cy2 = top_box
        overlap_x = max(0, min(px2, cx2) - max(px1, cx1))
        car_w = cx2 - cx1
        if car_w > 0 and (overlap_x / car_w) > 0.45:
            person_blocking_car = True

    if top_bw >= 280 and top_bh >= 180 and top_area >= 45000 and not person_blocking_car:
        x1, y1, x2, y2 = top_box
        crop = img[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        color = classify_color(crop)
        brand = classify_brand(crop)
        print(f"[AI] ⚠️ Gate vehicle detected, but plate unreadable ({color}, {brand}). Manual review available.")
        centering_bonus = 15.0 if (380 <= top_box[3] <= 620) else 0.0
        return {
            "success": False,
            "vehicle_detected": True,
            "plate": "UNKNOWN",
            "color": color,
            "brand": brand,
            "coords": [int(c) for c in top_box],
            "quality_score": 40.0 + (20.0 if brand != "Unknown" else 0.0) + centering_bonus,
            "message": "Vehicle in gate, but license plate is unreadable or obscured."
        }

    # Smaller / partial or ambiguous objects with unreadable plate are safely ignored
    print(f"[AI] ℹ️ Unverified object with unreadable plate (bw={top_bw}, bh={top_bh}, person={has_foreground_person}). Ignored to prevent false visit.")
    return {
        "success": False,
        "vehicle_detected": False,
        "plate": "UNKNOWN",
        "color": "Unknown",
        "brand": "Unknown",
        "coords": [0, 0, 0, 0],
        "quality_score": 0.0,
        "message": "Unverified object (ignored to prevent false visit)"
    }

