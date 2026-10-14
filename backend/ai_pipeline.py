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



def classify_color(vehicle_img) -> str:
    """
    Robust HSV-based color detection algorithm.
    Extracts the dominant body color of the vehicle, filtering out wheels and floor reflections.
    """
    if vehicle_img is None or vehicle_img.size == 0:
        return "Unknown"

    img_resized = cv2.resize(vehicle_img, (120, 120))
    h, w, _ = img_resized.shape
    center_crop = img_resized[int(h * 0.15):int(h * 0.70), int(w * 0.15):int(w * 0.85)]

    hsv = cv2.cvtColor(center_crop, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3)

    color_counts = {
        "White": 0, "Black": 0, "Grey/Silver": 0,
        "Red": 0, "Orange": 0, "Yellow": 0,
        "Green": 0, "Blue": 0, "Purple/Violet": 0
    }

    for h_val, s, v in pixels:
        if s < 50:  # Low saturation: Black / Grey / White
            if v > 180:
                color_counts["White"] += 1
            elif v < 70:
                color_counts["Black"] += 1
            else:
                color_counts["Grey/Silver"] += 1
        else:
            if (0 <= h_val < 10) or (160 <= h_val <= 180):
                color_counts["Red"] += 1
            elif 10 <= h_val < 25:
                color_counts["Orange"] += 1
            elif 25 <= h_val < 38:
                color_counts["Yellow"] += 1
            elif 38 <= h_val < 85:
                color_counts["Green"] += 1
            elif 85 <= h_val < 130:
                color_counts["Blue"] += 1
            elif 130 <= h_val < 160:
                color_counts["Purple/Violet"] += 1

    sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
    return sorted_colors[0][0]


def classify_brand(vehicle_img) -> str:
    """Default vehicle brand placeholder, editable in UI"""
    return "Toyota"


def run_ai_pipeline(image_path: str):
    """
    Full AI pipeline:
    1. Detect all candidate vehicles and pedestrians via YOLOv8.
    2. Try plate recognition on vehicle candidates (prioritizing vehicles with valid plates).
    3. If no plate found and foreground pedestrian detected, suppress as pedestrian motion.
    4. If vehicle found with plate, classify color & brand and return visit data.
    """
    init_models()
    img = cv2.imread(image_path)
    if img is None:
        return {
            "success": False,
            "plate": "UNKNOWN",
            "color": "Unknown",
            "brand": "Unknown",
            "coords": [0, 0, 0, 0],
            "message": "Failed to read image"
        }

    results = yolo_model(img, verbose=False, conf=0.18)
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

            # Vehicle classes: car (2), motorcycle (3), bus (5), truck (7)
            if cls_id in [2, 3, 5, 7]:
                score = conf * (area ** 0.5)
                candidate_vehicles.append((score, area, [x1, y1, x2, y2]))

    # Sort candidate vehicles by score (size and confidence)
    candidate_vehicles.sort(key=lambda x: x[0], reverse=True)

    best_plate = "UNKNOWN"
    selected_crop = None
    selected_box = None

    # Test OCR across candidate vehicles
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
        brand = classify_brand(selected_crop)
        print(f"[AI] ✅ Vehicle recognized! Plate: {best_plate}, Color: {color}, Brand: {brand}")
        return {
            "success": True,
            "vehicle_detected": True,
            "plate": best_plate,
            "color": color,
            "brand": brand,
            "coords": [int(c) for c in selected_box]
        }

    # If a vehicle was detected in the gate area, prioritize it over any pedestrians
    if candidate_vehicles and candidate_vehicles[0][1] >= 6000:
        box = candidate_vehicles[0][2]
        x1, y1, x2, y2 = box
        crop = img[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        color = classify_color(crop)
        brand = classify_brand(crop)
        print("[AI] ⚠️ Vehicle detected in gate, but license plate is unreadable/obscured.")
        return {
            "success": False,
            "vehicle_detected": True,
            "plate": "UNKNOWN",
            "color": color,
            "brand": brand,
            "coords": [int(c) for c in box],
            "message": "Vehicle detected in gate, but license plate is unreadable or obscured."
        }

    # If no vehicle was present, check if this was purely pedestrian motion
    if has_foreground_person:
        print("[AI] 🚶 Pedestrian motion detected at gate. Ignored.")
        return {
            "success": False,
            "vehicle_detected": False,
            "plate": "UNKNOWN",
            "color": "Unknown",
            "brand": "Unknown",
            "coords": [0, 0, 0, 0],
            "message": "Pedestrian motion detected at gate (ignored)"
        }

    return {
        "success": False,
        "vehicle_detected": False,
        "plate": "UNKNOWN",
        "color": "Unknown",
        "brand": "Unknown",
        "coords": [0, 0, 0, 0],
        "message": "No vehicle detected in gate area"
    }
