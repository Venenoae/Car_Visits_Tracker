import os
import re
import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO
import easyocr

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
    Cleans raw OCR text into standard UAE / GCC license plate formats:
    - Dubai: [Letter] [Digits] e.g. 'M 11770', 'C 90371', 'AA 1234'
    - Abu Dhabi: [Category] [Digits] e.g. '15 51913' -> '51913'
    - Sharjah / Northern Emirates: [1-4 / Letter] [Digits]
    - Plain Digits: 3 to 6 digits (e.g. '51913', '24384', '88874')
    """
    cleaned = re.sub(r'[^A-Z0-9\s]', '', raw_text.upper()).strip()
    words = [w for w in cleaned.split() if w not in IGNORED_WORDS and len(w) >= 1]
    cleaned = " ".join(words)

    # 1. Dubai Format: 1 or 2 letter code + 1 to 5 digits (e.g. 'M 11770', 'AA 1234', 'C 90371')
    match_dubai = re.search(r'\b([A-Z]{1,2})\s*([0-9OIl!SBZG]{1,5})\b', cleaned)
    if match_dubai:
        letter_code = match_dubai.group(1)
        raw_num = match_dubai.group(2)
        digits = disambiguate_digits(raw_num)
        if digits.isdigit() and 1 <= len(digits) <= 5:
            return f"{letter_code} {digits}", len(digits)

    # 2. Abu Dhabi Category Format: Category prefix + 3-6 digits (e.g. '15 51913' or '50 12345')
    match_ad = re.search(r'\b(?:1|2|3|4|5|6|7|8|9|10|11|12|14|15|16|17|50)\s+([0-9OIl!SBZG]{3,6})\b', cleaned)
    if match_ad:
        digits = disambiguate_digits(match_ad.group(1))
        if digits.isdigit():
            return digits, len(digits)

    # 3. Plain Numeric Plates: 3 to 6 digits (e.g. '51913', '24384', '88874')
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
                return f"{code} {digits}", len(digits)
        
        digit_count = sum(c.isdigit() for c in compact)
        if digit_count >= 3:
            return compact, len(compact)

    return None, 0


def extract_license_plate(vehicle_img) -> str:
    """
    Multi-pass OCR reader with glare reduction:
    Pass 1: Raw vehicle crop
    Pass 2: Lower bumper upscaled 2.5x with standard CLAHE
    Pass 3: Bilateral Filter + CLAHE (smooths glass reflections/headlight glare while keeping digits crisp)
    Pass 4: Otsu binarization
    Pass 5: High-contrast CLAHE (clipLimit=4.5) for shadowed plates
    """
    init_models()
    if vehicle_img is None or vehicle_img.size == 0:
        return "UNKNOWN"

    candidates = []

    # Pass 1: Raw vehicle crop
    results_raw = ocr_reader.readtext(vehicle_img)
    for (bbox, text, conf) in results_raw:
        plate_str, digit_count = clean_plate_candidate(text)
        if plate_str and conf > 0.15:
            score = conf + (digit_count * 0.15)
            candidates.append((plate_str, score))

    # Passes 2-5: Focused bumper region
    vh, vw = vehicle_img.shape[:2]
    if vh >= 40 and vw >= 60:
        bumper_crop = vehicle_img[int(vh * 0.35):vh, :]
        bumper_up = cv2.resize(bumper_crop, (0, 0), fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(bumper_up, cv2.COLOR_BGR2GRAY)

        # Pass 2: CLAHE (clipLimit=3.0)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enh = clahe.apply(gray)
        results_enh = ocr_reader.readtext(enh)
        for (bbox, text, conf) in results_enh:
            plate_str, digit_count = clean_plate_candidate(text)
            if plate_str and conf > 0.15:
                score = conf + (digit_count * 0.20) + 0.15
                candidates.append((plate_str, score))

        # Pass 3: Bilateral Filter + CLAHE (glare & reflection reduction)
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)
        clahe_bi = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
        enh_bi = clahe_bi.apply(denoised)
        results_bi = ocr_reader.readtext(enh_bi)
        for (bbox, text, conf) in results_bi:
            plate_str, digit_count = clean_plate_candidate(text)
            if plate_str and conf > 0.15:
                score = conf + (digit_count * 0.20) + 0.18
                candidates.append((plate_str, score))

        # Pass 4: Otsu Adaptive Binarization
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        results_otsu = ocr_reader.readtext(otsu)
        for (bbox, text, conf) in results_otsu:
            plate_str, digit_count = clean_plate_candidate(text)
            if plate_str and conf > 0.20:
                score = conf + (digit_count * 0.20) + 0.10
                candidates.append((plate_str, score))

        # Pass 5: High-contrast CLAHE (clipLimit=4.5) for dark/shadowed plates
        clahe_high = cv2.createCLAHE(clipLimit=4.5, tileGridSize=(8, 8))
        enh_high = clahe_high.apply(gray)
        results_high = ocr_reader.readtext(enh_high)
        for (bbox, text, conf) in results_high:
            plate_str, digit_count = clean_plate_candidate(text)
            if plate_str and conf > 0.15:
                score = conf + (digit_count * 0.20) + 0.12
                candidates.append((plate_str, score))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

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
    Classifies vehicle brand by searching OCR tokens for recognized brand emblems/badges.
    Returns 'Unknown' if no emblem text is detected, allowing fleet lookup or manual edit.
    """
    if raw_text_tokens:
        for token in raw_text_tokens:
            clean_tok = re.sub(r'[^A-Z]', '', token.upper())
            for brand in KNOWN_BRANDS:
                brand_clean = re.sub(r'[^A-Z]', '', brand)
                if brand_clean == clean_tok or (len(brand_clean) >= 5 and brand_clean in clean_tok):
                    return brand.title()

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

    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            bw = x2 - x1
            bh = y2 - y1
            area = bw * bh

            # Check for person in foreground / doorway
            if cls_id == 0 and y2 > 350:
                has_foreground_person = True

            # Strict Vehicle Qualification:
            # Classes: car (2), motorcycle (3), bus (5), truck (7)
            # Minimum confidence 0.35 and minimum dimensions 120x100
            if cls_id in [2, 3, 5, 7] and conf >= 0.35 and bw >= 120 and bh >= 100:
                score = conf * (area ** 0.5)
                candidate_vehicles.append((score, area, [x1, y1, x2, y2]))

    # If NO vehicle met the strict qualification criteria, ignore the capture entirely
    if not candidate_vehicles:
        if has_foreground_person:
            print("[AI] 🚶 Pedestrian motion detected at gate. Ignored.")
            return {
                "success": False,
                "vehicle_detected": False,
                "plate": "UNKNOWN",
                "color": "Unknown",
                "brand": "Unknown",
                "coords": [0, 0, 0, 0],
                "message": "Pedestrian motion at gate (ignored)"
            }
        return {
            "success": False,
            "vehicle_detected": False,
            "plate": "UNKNOWN",
            "color": "Unknown",
            "brand": "Unknown",
            "coords": [0, 0, 0, 0],
            "message": "No valid vehicle detected in gate area (non-vehicle object ignored)"
        }

    # Sort candidate vehicles by score (size and confidence)
    candidate_vehicles.sort(key=lambda x: x[0], reverse=True)

    best_plate = "UNKNOWN"
    selected_crop = None
    selected_box = None
    detected_tokens = []

    # Test OCR across qualified candidate vehicles
    for score, area, box in candidate_vehicles:
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
            "coords": [int(c) for c in selected_box]
        }

    # If vehicle was detected in gate, but license plate is obscured/unreadable
    top_score, top_area, top_box = candidate_vehicles[0]
    x1, y1, x2, y2 = top_box
    crop = img[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
    color = classify_color(crop)
    brand = classify_brand(crop)
    print(f"[AI] ⚠️ Vehicle detected in gate, but license plate is unreadable/obscured ({color}).")
    return {
        "success": False,
        "vehicle_detected": True,
        "plate": "UNKNOWN",
        "color": color,
        "brand": brand,
        "coords": [int(c) for c in top_box],
        "message": "Vehicle detected in gate, but license plate is unreadable or obscured."
    }

