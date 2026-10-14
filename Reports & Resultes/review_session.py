"""
Car Visits Tracker - Interactive ML Ground Truth Review Tool
Run this script at 12:00 PM to verify captured visits, calculate ML accuracy metrics,
and export ml_evaluation_results.md into 'Reports & Resultes/'.
"""

import os
import sys
import json
import sqlite3

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(BASE_DIR, "Reports & Resultes")
DATASET_PATH = os.path.join(REPORTS_DIR, "detailed_telemetry_dataset.json")
DB_PATH = os.path.join(BASE_DIR, "backend", "car_visits_tracker.db")

def run_review():
    print("="*70)
    print("🔍 CAR VISITS TRACKER - INTERACTIVE ML GROUND TRUTH REVIEW")
    print("="*70)

    records = []
    # Try loading from JSON dataset first
    if os.path.exists(DATASET_PATH):
        try:
            with open(DATASET_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for ev in data.get("events", []):
                    records.append(ev.get("data", {}))
        except Exception as e:
            print(f"Note: Could not load JSON dataset ({e}), reading from DB...")

    # Fallback to database visits if JSON empty
    if not records and os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT v.id, v.plate_number, v.zone, v.entry_timestamp, v.exit_timestamp,
                   v.entry_image_url, v.exit_image_url, v.status,
                   veh.color, veh.brand
            FROM visits v
            LEFT JOIN vehicles veh ON v.plate_number = veh.plate_number
            WHERE date(v.entry_timestamp) = '2026-10-15'
            ORDER BY v.id ASC
        """)
        for r in c.fetchall():
            records.append({
                "plate_number": r[1],
                "direction": "Entry" if r[3] else "Exit",
                "brand": r[9] or "Unknown",
                "color": r[8] or "Unknown",
                "image_url": r[5] or r[6]
            })
        conn.close()

    if not records:
        print("\n⚠️ No vehicle records found for review yet.")
        print("Please ensure the 10:00 AM - 12:00 PM session has completed or has active records.")
        return

    print(f"\nFound {len(records)} vehicles to review.")
    print("For each vehicle, press [ENTER] to confirm the AI prediction, or type the correction.\n")

    correct_plate = 0
    correct_brand = 0
    correct_dir = 0
    total = len(records)

    detailed_eval = []

    for i, r in enumerate(records, 1):
        ai_plate = r.get("plate_number", "UNKNOWN")
        ai_brand = r.get("brand", "Unknown")
        ai_color = r.get("color", "Unknown")
        ai_dir = r.get("direction", "Entry")
        img_url = r.get("image_url", "")

        print(f"\n[{i}/{total}] Vehicle Snapshot: {img_url}")
        print(f"  AI Detected: Plate: {ai_plate} | Brand: {ai_brand} | Color: {ai_color} | Direction: {ai_dir}")

        # 1. Plate Verification
        val_plate = input(f"  Plate [{ai_plate}] (Enter=correct, or type actual): ").strip()
        if not val_plate:
            actual_plate = ai_plate
            is_plate_ok = not (ai_plate.startswith("UNREADABLE-") or ai_plate == "UNKNOWN")
        else:
            actual_plate = val_plate
            is_plate_ok = (actual_plate.upper() == ai_plate.upper())

        if is_plate_ok:
            correct_plate += 1

        # 2. Brand Verification
        val_brand = input(f"  Brand [{ai_brand}] (Enter=correct, or type actual): ").strip()
        if not val_brand:
            actual_brand = ai_brand
            is_brand_ok = (ai_brand != "Unknown")
        else:
            actual_brand = val_brand
            is_brand_ok = (actual_brand.lower() == ai_brand.lower())

        if is_brand_ok:
            correct_brand += 1

        # 3. Direction Verification
        val_dir = input(f"  Direction [{ai_dir}] (Enter=correct, or type actual): ").strip()
        if not val_dir:
            actual_dir = ai_dir
            is_dir_ok = True
        else:
            actual_dir = val_dir
            is_dir_ok = (actual_dir.lower() == ai_dir.lower())

        if is_dir_ok:
            correct_dir += 1

        detailed_eval.append({
            "image": img_url,
            "ai_plate": ai_plate, "real_plate": actual_plate, "plate_ok": is_plate_ok,
            "ai_brand": ai_brand, "real_brand": actual_brand, "brand_ok": is_brand_ok,
            "ai_dir": ai_dir, "real_dir": actual_dir, "dir_ok": is_dir_ok
        })

    # Calculate Accuracies
    plate_acc = (correct_plate / total * 100) if total > 0 else 0
    brand_acc = (correct_brand / total * 100) if total > 0 else 0
    dir_acc = (correct_dir / total * 100) if total > 0 else 0

    print("\n" + "="*70)
    print("📊 MACHINE LEARNING EVALUATION SUMMARY")
    print("="*70)
    print(f"Total Vehicles Evaluated: {total}")
    print(f"Plate Accuracy:     {correct_plate}/{total} ({plate_acc:.1f}%)")
    print(f"Brand Accuracy:     {correct_brand}/{total} ({brand_acc:.1f}%)")
    print(f"Direction Accuracy: {correct_dir}/{total} ({dir_acc:.1f}%)")
    print("="*70)

    # Save to Markdown Report
    eval_path = os.path.join(REPORTS_DIR, "ml_evaluation_results.md")
    rows = ""
    for e in detailed_eval:
        p_badge = "✅" if e['plate_ok'] else "❌"
        b_badge = "✅" if e['brand_ok'] else "❌"
        d_badge = "✅" if e['dir_ok'] else "❌"
        rows += f"| `{e['image']}` | `{e['ai_plate']}` | `{e['real_plate']}` {p_badge} | {e['ai_brand']} | {e['real_brand']} {b_badge} | {e['ai_dir']} | {e['real_dir']} {d_badge} |\n"

    md = f"""# Verified Machine Learning Evaluation Report

**Evaluation Date**: October 15, 2026  
**Evaluator**: Human Ground Truth Verification  
**Total Samples**: {total}  

---

## 1. Overall Model Accuracies

| Dimension | Correct | Total | Accuracy (%) |
| :--- | :--- | :--- | :--- |
| **UAE License Plate OCR** | {correct_plate} | {total} | **{plate_acc:.1f}%** |
| **Vehicle Brand Recognition** | {correct_brand} | {total} | **{brand_acc:.1f}%** |
| **Direction (Entry vs. Exit)** | {correct_dir} | {total} | **{dir_acc:.1f}%** |

---

## 2. Sample-by-Sample Breakdown

| Image File | AI Plate | Real Plate | AI Brand | Real Brand | AI Dir | Real Dir |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{rows}

---

## 3. Conclusions & Retraining Plan
- Data logged in `Reports & Resultes/detailed_telemetry_dataset.json`.
- Edge cases identified above will be used to calibrate EasyOCR character whitening and MOG2 motion filters.
"""
    with open(eval_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n✅ ML Evaluation report generated: {eval_path}")

if __name__ == "__main__":
    run_review()
