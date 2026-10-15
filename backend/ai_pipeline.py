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
    """Thread-safe initialization of AI models with automatic GPU/CPU selection"""
    global yolo_model, ocr_reader
    with _init_lock:
        import torch
        use_gpu = torch.cuda.is_available()
        if yolo_model is None:
            print(f"[AI] Loading YOLOv8 nano detector (GPU={use_gpu})...")
            yolo_model = YOLO("yolov8n.pt")
            if use_gpu:
                yolo_model.to("cuda")
            
        if ocr_reader is None:
            print(f"[AI] Loading EasyOCR reader (GPU={use_gpu})...")
            ocr_reader = easyocr.Reader(['en'], gpu=use_gpu, verbose=False)


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


def normalize_plate_number(raw_plate: str) -> str:
    """
    Canonical UAE license plate normalizer shared across AI pipeline and manual API endpoints.
    Preserves a single space between the Emirate letter/category prefix and the plate digits:
      - 'B7238' or 'b 7238' -> 'B 7238'
      - '10 55456' or '10-55456' -> '10 55456'
      - 'UNREADABLE-123456' -> 'UNREADABLE-123456'
    """
    if not raw_plate:
        return "UNKNOWN"
    upper = raw_plate.strip().upper()
    if upper.startswith("UNREADABLE-") or upper.startswith("CAR-") or upper == "UNKNOWN":
        return upper

    cleaned = re.sub(r'[^A-Z0-9\s]', ' ', upper)
    tokens = [t for t in cleaned.split() if t and t not in IGNORED_WORDS]
    if not tokens:
        return re.sub(r'[^A-Z0-9]', '', upper) or "UNKNOWN"

    joined = " ".join(tokens)
    # 1. Abu Dhabi / Numeric Category + Digits (e.g. '10 55456')
    m_ad = re.match(r'^(1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17|18|19|20|50)\s+([0-9]{2,6})$', joined)
    if m_ad:
        return f"{m_ad.group(1)} {m_ad.group(2)}"

    # 2. Dubai / Northern Emirates Letter Prefix + Digits (e.g. 'B 7238', 'AA 12345', 'B7238')
    compact = re.sub(r'\s+', '', joined)
    m_let = re.match(r'^([A-Z]{1,2})([0-9]{1,6})$', compact)
    if m_let:
        return f"{m_let.group(1)} {m_let.group(2)}"

    # 3. Reverse order (Digits + Letter Code) -> normalize to 'CODE DIGITS'
    m_rev = re.match(r'^([0-9]{1,6})([A-Z]{1,2})$', compact)
    if m_rev:
        return f"{m_rev.group(2)} {m_rev.group(1)}"

    return compact


def clean_plate_candidate(raw_text: str):
    """
    Cleans raw OCR text into standard UAE license plate formats:
    - Abu Dhabi: [Category] [Digits] e.g. '10 55456', '4 12345', '50 9999'
    - Dubai: [Letter(s)] [Digits] e.g. 'B 7238', 'M 11770', 'AA 1234', 'C 90371'
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

    # 2. Dubai Format: 1 or 2 letter code + 1 to 5 digits (e.g. 'B 7238', 'M 11770', 'AA 1234')
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


def _refine_plate_digits(num_zone: np.ndarray, num_raw: np.ndarray, digits_str: str) -> str:
    """
    Structural glyph disambiguator for UAE plate numbers under motion blur:
    1. Leading '1' vs '7': In the UAE plate font, '7' has a wide top horizontal bar,
       whereas '1' is a narrow vertical stem.
    2. Trailing '0' vs '8': Aggressive unsharp masking can erode the middle crossbar of '8'
       into '0'; checks the raw un-haloed center waist of trailing '0'.
    """
    if not digits_str or len(digits_str) < 3:
        return digits_str

    chars = list(digits_str)
    nh, nw = num_zone.shape[:2]

    # 1. Check leading '1' vs '7'
    if chars[0] == '1' and nh >= 12 and nw >= 24:
        _, bw = cv2.threshold(num_zone, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        sub = bw[:, :int(nw * 0.32)]
        cols = np.where(np.sum(sub > 0, axis=0) >= max(2, int(nh * 0.12)))[0]
        if len(cols) >= 4:
            glyph = sub[:, cols[0]:cols[-1]+1]
            rows = np.where(np.sum(glyph > 0, axis=1) >= 2)[0]
            if len(rows) >= 8:
                glyph = glyph[rows[0]:rows[-1]+1, :]
                gh, gw = glyph.shape
                top_band = glyph[:max(2, int(gh * 0.30)), :]
                bot_band = glyph[int(gh * 0.65):, :]
                top_w = np.sum(np.any(top_band > 0, axis=0))
                bot_w = np.sum(np.any(bot_band > 0, axis=0))
                top_fill = float(np.mean(top_band > 0))
                if (top_w >= bot_w * 1.15 and top_fill >= 0.40) or (gw / float(gh) >= 0.42 and top_fill >= 0.45):
                    chars[0] = '7'

    # 2. Check trailing '0' vs '8' on raw grayscale (avoids unsharp halo erosion of '8' waist)
    if chars[-1] == '0' and num_raw is not None and num_raw.size > 0:
        rh, rw = num_raw.shape[:2]
        raw_norm = cv2.normalize(num_raw, None, 0, 255, cv2.NORM_MINMAX)
        t_val = int(np.percentile(raw_norm, 45))
        bw_raw = (raw_norm < t_val).astype(np.uint8)
        last_sub = bw_raw[:, int(rw * 0.70):]
        cols = np.where(np.sum(last_sub > 0, axis=0) >= max(2, int(rh * 0.15)))[0]
        if len(cols) >= 4:
            glyph = last_sub[:, cols[0]:cols[-1]+1]
            rows = np.where(np.sum(glyph > 0, axis=1) >= 2)[0]
            if len(rows) >= 8:
                glyph = glyph[rows[0]:rows[-1]+1, :]
                gh, gw = glyph.shape
                mid_waist = float(np.mean(glyph[int(gh * 0.38):int(gh * 0.62), int(gw * 0.25):int(gw * 0.75)]))
                if mid_waist >= 0.35:
                    chars[-1] = '8'

    return "".join(chars)


def _resolve_dubai_prefix(code_raw: np.ndarray, ocr_chars: str):
    """
    Resolves the bottom-left Emirate letter code on a UAE plate (underneath 'DUBAI').
    At 1280x720 gate distance, the letter is ~11x9 px natively, where 'B' is often
    read by CRNN as '8', '0', 'D', or 'B'. Uses center-waist bar density to distinguish 'B'.
    """
    if code_raw is None or code_raw.size == 0:
        return None
    code_up = cv2.resize(code_raw, (60, 60), interpolation=cv2.INTER_CUBIC)
    code_norm = cv2.normalize(code_up, None, 0, 255, cv2.NORM_MINMAX)
    t_val = int(np.percentile(code_norm, 42))
    bw = (code_norm < t_val).astype(np.uint8)
    bw[:4, :] = 0; bw[-4:, :] = 0; bw[:, :4] = 0; bw[:, -4:] = 0
    ys, xs = np.where(bw > 0)
    if len(xs) < 20:
        return None
    glyph = bw[ys.min():ys.max()+1, xs.min():xs.max()+1]
    gh, gw = glyph.shape
    if gh < 12 or gw < 8:
        return None

    left_spine = float(np.mean(glyph[:, :max(2, int(gw * 0.32))]))
    mid_waist = float(np.mean(glyph[int(gh * 0.38):int(gh * 0.62), int(gw * 0.25):int(gw * 0.78)]))
    top_bar = float(np.mean(glyph[:max(2, int(gh * 0.25)), :]))
    bot_bar = float(np.mean(glyph[int(gh * 0.75):, :]))

    clean_ocr = re.sub(r'[^A-Z0-9]', '', ocr_chars.upper())
    if any(c in clean_ocr for c in ('8', 'B', '0', 'D', '3', '6', 'R', 'E')):
        if mid_waist >= 0.32 and left_spine >= 0.45 and top_bar >= 0.35 and bot_bar >= 0.35:
            return 'B'
        if 'D' in clean_ocr or '0' in clean_ocr:
            return 'B' if mid_waist >= 0.30 else 'D'
        if '8' in clean_ocr or 'B' in clean_ocr:
            return 'B'
    if left_spine >= 0.50 and mid_waist >= 0.35 and top_bar >= 0.40 and bot_bar >= 0.40:
        return 'B'
    for ch in clean_ocr:
        if 'A' <= ch <= 'Z':
            return ch
    return None


def _extract_uae_split_plate(vehicle_img) -> str:
    """
    Dedicated UAE Split-Level License Plate Locator & Reader:
    1. Detects the white license plate rectangle in the lower half of the vehicle crop,
       filtering out blown-out LED headlights and non-plate body panels.
    2. Isolates the plate interior (4x Lanczos upscaled) and masks out the bottom-right
       registration sticker (x > 89%) and top-left 'DUBAI' header.
    3. Reads the 3-5 main plate digits using multi-pass Otsu, Percentile-42, and Stitched OCR
       with structural disambiguation for '7' vs '1' and '8' vs '0'.
    4. Resolves the left-hand Emirate letter prefix (e.g. 'B' in 'DUBAI B 7238').
    """
    vh, vw = vehicle_img.shape[:2]
    if vh < 80 or vw < 160:
        return "UNKNOWN"

    y_off = int(vh * 0.50)
    sub = vehicle_img[y_off:vh, :]
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 120), (180, 75, 255))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    plate_cnts = []
    for cnt in cnts:
        rx, ry, rw, rh = cv2.boundingRect(cnt)
        aspect = rw / float(rh) if rh > 0 else 0
        if 2.3 <= aspect <= 5.8 and 60 <= rw <= 210 and 15 <= rh <= 68:
            if vw * 0.15 <= (rx + rw / 2.0) <= vw * 0.85:
                roi_v = hsv[ry:ry+rh, rx:rx+rw, 2]
                roi_s = hsv[ry:ry+rh, rx:rx+rw, 1]
                # Reject blown-out LED headlights
                if np.mean(roi_v >= 250) > 0.50:
                    continue
                dark_ratio = float(np.mean((roi_v < 115) & (roi_s < 90)))
                if not (0.05 <= dark_ratio <= 0.45):
                    continue
                plate_cnts.append((rw * rh, rx, ry, rw, rh))

    plate_cnts.sort(reverse=True)
    for _, rx, ry, rw, rh in plate_cnts[:3]:
        p_crop = sub[max(0, ry-8):min(sub.shape[0], ry+rh+8), max(0, rx-8):min(sub.shape[1], rx+rw+8)]
        p_up = cv2.resize(p_crop, (0, 0), fx=4.0, fy=4.0, interpolation=cv2.INTER_LANCZOS4)
        hsv_up = cv2.cvtColor(p_up, cv2.COLOR_BGR2HSV)
        white_mask = cv2.inRange(hsv_up, (0, 0, 120), (180, 75, 255))
        ys, xs = np.where(white_mask > 0)
        if len(xs) < 100 or len(ys) < 100:
            continue
        x_min, x_max = int(np.percentile(xs, 3)), int(np.percentile(xs, 97))
        y_min, y_max = int(np.percentile(ys, 5)), int(np.percentile(ys, 95))
        if (x_max - x_min) < 80 or (y_max - y_min) < 25:
            continue

        interior = p_up[y_min:y_max, x_min:x_max]
        ih, iw = interior.shape[:2]
        gray = cv2.cvtColor(interior, cv2.COLOR_BGR2GRAY)

        blur = cv2.GaussianBlur(gray, (0, 0), 3.0)
        sharp = cv2.addWeighted(gray, 2.5, blur, -1.5, 0)
        sharp_norm = cv2.normalize(sharp, None, 0, 255, cv2.NORM_MINMAX)

        # Right digit zone (x: 36%..89% avoids left code & bottom-right registration sticker)
        num_zone = sharp_norm[int(ih*0.12):int(ih*0.88), int(iw*0.36):int(iw*0.89)]
        num_raw = gray[int(ih*0.12):int(ih*0.88), int(iw*0.36):int(iw*0.89)]
        if num_zone.size == 0 or num_raw.size == 0:
            continue

        _, otsu = cv2.threshold(num_zone, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        num_raw_norm = cv2.normalize(num_raw, None, 0, 255, cv2.NORM_MINMAX)
        p42_bin = np.where(num_raw_norm < np.percentile(num_raw_norm, 42), 0, 255).astype(np.uint8)

        pad_otsu = cv2.copyMakeBorder(otsu, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        pad_p42 = cv2.copyMakeBorder(p42_bin, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        pad_gray = cv2.copyMakeBorder(num_zone, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=int(np.percentile(num_zone, 85)))

        digit_reads = []
        for img_v in (pad_otsu, pad_p42, pad_gray):
            for _, t, c in ocr_reader.readtext(img_v, allowlist="0123456789", min_size=3, text_threshold=0.2, low_text=0.15):
                d = re.sub(r'[^0-9]', '', t)
                if 3 <= len(d) <= 5:
                    digit_reads.append((d, float(c)))
            for _, t, c in ocr_reader.recognize(img_v, allowlist="0123456789", detail=1):
                d = re.sub(r'[^0-9]', '', t)
                if 3 <= len(d) <= 5:
                    digit_reads.append((d, float(c)))

        code_raw = gray[int(ih*0.55):int(ih*0.93), int(iw*0.11):int(iw*0.30)]
        nh, nw = num_raw.shape[:2]
        code_canvas = None
        if code_raw.size > 0 and nh >= 16:
            ch, cw = code_raw.shape[:2]
            target_ch = int(nh * 0.85)
            target_cw = max(16, int(cw * (target_ch / float(max(ch, 1)))))
            code_up = cv2.resize(code_raw, (target_cw, target_ch), interpolation=cv2.INTER_CUBIC)
            code_norm = cv2.normalize(code_up, None, 0, 255, cv2.NORM_MINMAX)
            t_val = int(np.percentile(code_norm, 38))
            code_bin = np.where(code_norm < t_val, 0, 255).astype(np.uint8)
            code_canvas = np.full((nh, target_cw), 255, dtype=np.uint8)
            y_pad = (nh - target_ch) // 2
            code_canvas[y_pad:y_pad+target_ch, :] = code_bin

            spacer = np.full((nh, 18), 255, dtype=np.uint8)
            stitched = np.hstack([code_canvas, spacer, p42_bin])
            stitched_pad = cv2.copyMakeBorder(stitched, 20, 20, 24, 24, cv2.BORDER_CONSTANT, value=255)
            for _, t, c in ocr_reader.readtext(stitched_pad, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ", min_size=3, text_threshold=0.2, low_text=0.15):
                m_d = re.findall(r'[0-9]{3,5}', t)
                if m_d:
                    digit_reads.append((m_d[-1], float(c) + 0.15))

        if not digit_reads:
            continue

        digit_reads.sort(key=lambda item: (len(item[0]) == 4, len(item[0]), item[1]), reverse=True)
        best_digits, best_conf = digit_reads[0]
        if best_conf < 0.35:
            continue

        # Cross-check if any high-confidence read already resolved '7' at start or '8' at end
        if best_digits.startswith('1'):
            alt_seven = '7' + best_digits[1:]
            if any(d == alt_seven and c >= 0.30 for d, c in digit_reads):
                best_digits = alt_seven
        if best_digits.endswith('0'):
            alt_eight = best_digits[:-1] + '8'
            if any(d.endswith('8') and len(d) == len(best_digits) and c >= 0.35 for d, c in digit_reads):
                best_digits = alt_eight

        best_digits = _refine_plate_digits(num_zone, num_raw, best_digits)

        # Check top-left header for Dubai/Emirate plate
        top_left = gray[int(ih*0.12):int(ih*0.46), int(iw*0.08):int(iw*0.33)]
        has_top_header = float(np.mean(top_left < np.percentile(gray, 55))) > 0.15
        prefix = None
        if has_top_header and code_raw.size > 0 and code_canvas is not None:
            code_pad = cv2.copyMakeBorder(code_canvas, 18, 18, 18, 18, cv2.BORDER_CONSTANT, value=255)
            rec_c = ocr_reader.recognize(code_pad, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", detail=1)
            ocr_c_str = rec_c[0][1] if rec_c else ""
            prefix = _resolve_dubai_prefix(code_raw, ocr_c_str)

        return normalize_plate_number(f"{prefix} {best_digits}" if prefix else best_digits)

    return "UNKNOWN"


def extract_license_plate(vehicle_img) -> str:
    """
    Multi-pass UAE License Plate OCR Reader:
    1. First runs the dedicated UAE Split-Level Plate Contour Locator & Reader
       (handles 2-row left Emirate header+letter and 4-5 right digits such as 'DUBAI B 7238').
    2. Falls back to multi-pass lower-bumper OCR with horizontal clustering and category expansion.
    """
    init_models()
    if vehicle_img is None or vehicle_img.size == 0:
        return "UNKNOWN"

    # Pass 0: Dedicated UAE Split-Level Plate Contour Locator
    split_plate = _extract_uae_split_plate(vehicle_img)
    if split_plate != "UNKNOWN":
        return split_plate

    candidates = []
    category_prefixes = []
    vh, vw = vehicle_img.shape[:2]

    # Sample lower bumper area (where plates are mounted)
    bumper_crop = vehicle_img[int(vh * 0.35):vh, :] if vh >= 40 else vehicle_img
    
    gray = cv2.cvtColor(bumper_crop, cv2.COLOR_BGR2GRAY)
    passes = [
        ("clahe", cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(cv2.resize(gray, (0, 0), fx=1.25, fy=1.25, interpolation=cv2.INTER_CUBIC))),
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
            clean_t = text.strip()
            boxes.append({'text': clean_t, 'cx': cx, 'cy': cy, 'h': h, 'w': w, 'box': [bx1, by1, bx2, by2], 'conf': conf})

            # Detect standalone Abu Dhabi / UAE category badges (1-20, 50)
            if clean_t.isdigit() and int(clean_t) in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 50]:
                category_prefixes.append((clean_t, conf, [bx1, by1, bx2, by2]))

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

    # Cross-reference candidates and expand prefixes:
    final_candidates = []
    for plate_str, score, cl in candidates:
        if " " not in plate_str and plate_str.isdigit():
            min_x = min(item['box'][0] for item in cl)
            max_x = max(item['box'][2] for item in cl)
            min_y = min(item['box'][1] for item in cl)
            max_y = max(item['box'][3] for item in cl)
            bw = max_x - min_x
            bh = max_y - min_y

            # 1. Match with any category prefix found to the left on the same baseline
            found_cat = None
            for cat_num, cat_conf, cat_box in category_prefixes:
                if cat_box[2] <= min_x + bw * 0.25 and (min_x - cat_box[0]) < bw * 1.5:
                    cat_cy = (cat_box[1] + cat_box[3]) / 2.0
                    digit_cy = (min_y + max_y) / 2.0
                    if abs(cat_cy - digit_cy) < max(bh, cat_box[3] - cat_box[1]) * 1.2:
                        found_cat = cat_num
                        break

            if found_cat:
                combined_plate = f"{found_cat} {plate_str}"
                final_candidates.append((combined_plate, score + 4.0))
                continue

            # 2. Check prefix crop to the left with bilateral/CLAHE filter
            ex_x1 = max(0, int(min_x - bw * 1.3))
            ex_x2 = min(bumper_crop.shape[1], int(max_x + bw * 0.2))
            ex_y1 = max(0, int(min_y - bh * 0.3))
            ex_y2 = min(bumper_crop.shape[0], int(max_y + bh * 0.3))

            expanded_sub = bumper_crop[ex_y1:ex_y2, ex_x1:ex_x2]
            if expanded_sub.size > 0:
                sub_gray = cv2.cvtColor(expanded_sub, cv2.COLOR_BGR2GRAY)
                sub_proc = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8)).apply(
                    cv2.bilateralFilter(cv2.resize(sub_gray, (0, 0), fx=2.0, fy=2.0), 9, 75, 75)
                )
                sub_res = ocr_reader.readtext(sub_proc)
                sub_items = []
                for s_bbox, s_text, s_conf in sub_res:
                    s_cx = (s_bbox[0][0] + s_bbox[1][0]) / 2.0
                    sub_items.append((s_cx, s_text, s_conf))
                sub_items.sort(key=lambda x: x[0])
                expanded_joined = " ".join(x[1] for x in sub_items)
                exp_plate, exp_bonus = clean_plate_candidate(expanded_joined)
                if exp_plate and " " in exp_plate:
                    cat_prefix = exp_plate.split()[0]
                    # Retain full plate_str digits
                    combined_plate = f"{cat_prefix} {plate_str}"
                    final_candidates.append((combined_plate, score + 3.0))
                    continue

        elif " " in plate_str:
            parts = plate_str.split()
            cat = parts[0]
            short_digits = parts[1]
            # See if another candidate has longer digits that encompass short_digits
            for other_str, other_score, _ in candidates:
                if " " not in other_str and other_str.isdigit() and len(other_str) > len(short_digits):
                    if short_digits[0] == other_str[0] and short_digits[-1] == other_str[-1]:
                        plate_str = f"{cat} {other_str}"
                        score += 3.0
                        break
            final_candidates.append((plate_str, score))
            continue

        final_candidates.append((plate_str, score))

    if final_candidates:
        final_candidates.sort(key=lambda x: x[1], reverse=True)
        return normalize_plate_number(final_candidates[0][0])

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
    Samples the lower-middle body panel (40%-78% height, 18%-82% width) below the dark
    tinted side windows and filters out indoor showroom ceiling light reflections.
    Classifies into the Standard Automotive Palette:
    White, Black, Silver/Grey, Blue, Red, Brown/Gold, Green, Yellow
    """
    if vehicle_img is None or vehicle_img.size == 0:
        return "Unknown"

    vh, vw = vehicle_img.shape[:2]
    y_start, y_end = int(vh * 0.40), int(vh * 0.78)
    x_start, x_end = int(vw * 0.18), int(vw * 0.82)

    if y_end <= y_start or x_end <= x_start:
        body_crop = vehicle_img
    else:
        body_crop = vehicle_img[y_start:y_end, x_start:x_end]

    img_resized = cv2.resize(body_crop, (100, 100))
    hsv = cv2.cvtColor(img_resized, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3)

    s_vals = pixels[:, 1]
    v_vals = pixels[:, 2]

    # 1. White paint check: predominantly bright and low-saturation across the lower body panel
    low_sat_mask = (s_vals < 45) & (v_vals > 45)
    if np.sum(low_sat_mask) > len(pixels) * 0.40:
        low_sat_v = v_vals[low_sat_mask]
        if np.mean(low_sat_v > 155) > 0.25 and np.median(low_sat_v) > 125:
            return "White"

    # 2. Glossy Black paint check: under bright showroom LED strips, black paint has a dark
    #    base (25th percentile V < 75 or >=28% pixels with V < 88) without large bright white door panels
    if np.median(s_vals) < 52:
        dark_ratio = float(np.mean((v_vals < 88) & (s_vals < 70)))
        very_bright_ratio = float(np.mean((v_vals > 155) & (s_vals < 42)))
        if (dark_ratio >= 0.28 or np.percentile(v_vals, 25) < 72) and very_bright_ratio < 0.20:
            return "Black"

    color_counts = {
        "White": 0, "Black": 0, "Silver/Grey": 0,
        "Red": 0, "Blue": 0, "Brown/Gold": 0,
        "Green": 0, "Yellow": 0
    }

    for h_val, s, v in pixels:
        # Filter out blown-out overhead fluorescent/LED tube reflections
        if v > 220 and s < 25:
            continue

        if s < 42:  # Low saturation: Black / Silver/Grey / White
            if v > 152:
                color_counts["White"] += 1
            elif v < 88:
                color_counts["Black"] += 1
            else:
                color_counts["Silver/Grey"] += 1
        else:  # Saturated colors
            if v < 40:
                color_counts["Black"] += 1
            elif (0 <= h_val < 10) or (160 <= h_val <= 180):
                color_counts["Red"] += 1
            elif 10 <= h_val < 38:
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
    1. Scans front grille & lower trunk badge area (42%-82% height, 22%-78% width,
       avoiding the upper windshield/window background where outside signs appear).
    2. Runs EasyOCR on 2x upscaled and CLAHE-enhanced badge crops.
    3. Recognizes performance sub-brands (e.g. NISMO -> Nissan, AMG -> Mercedes-Benz).
    4. Detects Nissan Patrol Nismo signature red-accented lower bumper trim + central V-motion grille emblem.
    """
    init_models()
    if vehicle_img is None or vehicle_img.size == 0:
        return "Unknown"

    vh, vw = vehicle_img.shape[:2]
    grille_crop = vehicle_img[int(vh * 0.42):int(vh * 0.82), int(vw * 0.22):int(vw * 0.78)]
    if grille_crop.shape[0] >= 20 and grille_crop.shape[1] >= 30:
        grille_up = cv2.resize(grille_crop, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        grille_gray = cv2.cvtColor(grille_up, cv2.COLOR_BGR2GRAY)
        grille_clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(6, 6)).apply(grille_gray)

        best_brand = "Unknown"
        best_sim = 0.0

        for proc in (grille_up, grille_clahe):
            res = ocr_reader.readtext(proc)
            for bbox, text, conf in res:
                clean_t = re.sub(r'[^A-Z]', '', text.upper())
                if not clean_t:
                    continue

                if "NISMO" in clean_t or "NISSAN" in clean_t or clean_t in ("NISS", "SSAN"):
                    return "Nissan"
                if "AMG" in clean_t:
                    return "Mercedes-Benz"
                if "LEXUS" in clean_t:
                    return "Lexus"

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

        # Visual signature check for Nissan Patrol Nismo:
        # Dark honeycomb grille with central circular emblem + crimson Nismo lower bumper lip & side vents
        lower_lip = vehicle_img[int(vh * 0.72):int(vh * 0.98), int(vw * 0.12):int(vw * 0.88)]
        center_emblem = vehicle_img[int(vh * 0.42):int(vh * 0.68), int(vw * 0.32):int(vw * 0.62)]
        if lower_lip.size > 0 and center_emblem.size > 0:
            hsv_lip = cv2.cvtColor(lower_lip, cv2.COLOR_BGR2HSV)
            red_mask1 = cv2.inRange(hsv_lip, (0, 65, 35), (12, 255, 255))
            red_mask2 = cv2.inRange(hsv_lip, (165, 65, 35), (180, 255, 255))
            red_lip_ratio = float(np.mean((red_mask1 > 0) | (red_mask2 > 0)))
            emb_gray = cv2.cvtColor(center_emblem, cv2.COLOR_BGR2GRAY)
            emb_edges = float(np.mean(np.abs(cv2.Sobel(emb_gray, cv2.CV_32F, 1, 0, ksize=3)) > 30))
            if 0.002 <= red_lip_ratio <= 0.16 and emb_edges >= 0.08:
                return "Nissan"

    return "Unknown"


def run_ai_pipeline(image_path: str):
    """
    Strict Vehicle AI Pipeline:
    1. Detect candidate vehicles using YOLOv8 with strict qualification:
       - Confidence >= 0.35
       - Entryway floor sill threshold: y2 >= 410 (strictly rejects cars parked outside on ramp/behind glass)
       - Strictly Vehicle classes: car (2), motorcycle (3), bus (5), truck (7)
       - Distinguishes drivers inside vehicles / bystanders behind vehicles from standalone walking pedestrians.
    2. Runs multi-pass UAE Split-Level & Bumper OCR on candidate vehicle crops.
    3. Classifies body paint color and brand.
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
    person_boxes = []

    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            bw = x2 - x1
            bh = y2 - y1
            area = bw * bh

            # Collect foreground/midground person boxes
            if cls_id == 0 and y2 > 250 and conf >= 0.30:
                person_boxes.append([x1, y1, x2, y2, area])

            # Vehicle Classes: car (2), motorcycle (3), bus (5), truck (7)
            if cls_id in [2, 3, 5, 7] and conf >= 0.35:
                # 1. Active Doorway Floor Sill Threshold (y2 >= 410):
                #    The physical sliding door threshold sits at y=430px.
                #    Cars parked outside on the ramp (e.g. Porsche at y2=289, Land Cruiser at y2=280)
                #    or behind the fixed glass wall (y2 <= 380) never reach y2 >= 410.
                if y2 < 410:
                    continue

                # 2. Driveway Lane Corridor Filter:
                #    Completely ignores the permanently parked white Nissan Patrol in the left showroom bay.
                cx = (x1 + x2) // 2
                if x1 < 250 and (x2 < 900 or cx < 550):
                    continue
                if cx < 380 or cx > 1200 or x2 < 380 or x1 > 1180:
                    continue

                # 3. Minimum vehicle dimensions in entryway
                if bw >= 220 and bh >= 140:
                    score = conf * (area ** 0.5)
                    candidate_vehicles.append((score, area, bw, bh, [x1, y1, x2, y2]))

    # Deduplicate overlapping YOLO boxes for the same physical vehicle (e.g. 'car' + 'truck' on same SUV)
    deduped_vehicles = []
    for cand in sorted(candidate_vehicles, key=lambda x: x[0], reverse=True):
        _, c_area, _, _, c_box = cand
        is_dup = False
        for _, _, _, _, ex_box in deduped_vehicles:
            ix1 = max(c_box[0], ex_box[0])
            iy1 = max(c_box[1], ex_box[1])
            ix2 = min(c_box[2], ex_box[2])
            iy2 = min(c_box[3], ex_box[3])
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            if inter / float(max(c_area, 1)) > 0.65:
                is_dup = True
                break
        if not is_dup:
            deduped_vehicles.append(cand)
    candidate_vehicles = deduped_vehicles

    # If NO vehicle is in the active gate corridor, ignore the capture entirely
    if not candidate_vehicles:
        if person_boxes:
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

    best_plate = "UNKNOWN"
    selected_crop = None
    selected_box = None
    detected_tokens = []

    # Test OCR across qualified candidate vehicles in gate
    for score, area, bw, bh, box in candidate_vehicles:
        x1, y1, x2, y2 = box
        # First try exact vehicle crop (keeps relative plate coordinates exact), then padded crop
        for pad_ratio in (0.0, 0.05):
            pad_x = int((x2 - x1) * pad_ratio)
            pad_y = int((y2 - y1) * pad_ratio)
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
        if best_plate != "UNKNOWN":
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

    # If no readable plate, check whether a genuine large vehicle occupies the entryway vs a walking person
    top_score, top_area, top_bw, top_bh, top_box = candidate_vehicles[0]
    cx1, cy1, cx2, cy2 = top_box

    # Determine if any detected person is an independent foreground pedestrian blocking/causing the trigger
    # (Ignore drivers sitting inside the car window or distant staff standing behind a huge vehicle!)
    blocking_pedestrian = False
    for px1, py1, px2, py2, p_area in person_boxes:
        ix1 = max(px1, cx1)
        iy1 = max(py1, cy1)
        ix2 = min(px2, cx2)
        iy2 = min(py2, cy2)
        inter_area = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        inside_car_ratio = inter_area / float(max(p_area, 1))

        # Driver inside car window (e.g. 19:07:31) or person standing behind car in background (e.g. 19:31:31)
        if inside_car_ratio >= 0.70 and top_area > p_area * 3.5:
            continue
        if cy2 > py2 + 80 and top_area > p_area * 4.0:
            continue

        # Person standing in front of car in foreground
        if py2 >= cy2 - 30 and p_area >= top_area * 0.35:
            blocking_pedestrian = True
            break

    if blocking_pedestrian:
        print("[AI] 🚶 Pedestrian / staff motion in gate area with no readable plate. Ignored to prevent false visit.")
        return {
            "success": False,
            "vehicle_detected": False,
            "plate": "UNKNOWN",
            "color": "Unknown",
            "brand": "Unknown",
            "coords": [0, 0, 0, 0],
            "message": "Pedestrian / staff motion in gate (ignored)"
        }

    if top_bw >= 280 and top_bh >= 180 and top_area >= 45000:
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
    print(f"[AI] ℹ️ Unverified object with unreadable plate (bw={top_bw}, bh={top_bh}). Ignored to prevent false visit.")
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


