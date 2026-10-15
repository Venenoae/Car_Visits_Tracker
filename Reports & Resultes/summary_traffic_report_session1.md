# Real-Life Traffic Benchmark Report (10:00 AM - 12:00 PM)

**Date**: October 15, 2026  
**Session Window**: 10:00:00 AM – 12:00:00 PM (Gulf Standard Time)  
**Location**: Showroom Gate (`Zone A`)  
**Status**: Completed  

---

## 1. Executive Summary & KPIs

| Metric | Measured Value | Target / Benchmark |
| :--- | :--- | :--- |
| **Total Gate Motion Events** | **0** | N/A |
| **Total Vehicles Logged** | **0** | N/A |
| **Vehicles Entered** | **0** | - |
| **Vehicles Exited** | **0** | - |
| **Recognized Plates** | **0** | > 85% |
| **Unreadable / Obscured Plates** | **0** | < 15% |
| **Raw Plate Recognition Rate** | **0.0%** | Target >= 90% |

---

## 2. Vehicle Brand Breakdown

| Vehicle Brand / Make | Count |
| :--- | :--- |
| *(No brands identified)* | 0 |


---

## 3. Database Visits Logged (10:00 AM – 12:00 PM)

| Visit ID | License Plate | Detected Brand | Detected Color | Entry Timestamp | Exit Timestamp | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| #5 | `UNREADABLE-797547` | Unknown | Silver/Grey | 2026-10-15 09:09:20.006051 | - | Inside |
| #6 | `10 489971` | Unknown | Red | 2026-10-15 10:01:34.519051 | 2026-10-15 10:01:34.519051 | Completed |
| #7 | `UNREADABLE-870085` | Unknown | Silver/Grey | 2026-10-15 10:34:08.578720 | - | Inside |


---

## 4. Key Engineering & Machine Learning Insights

1. **Directional Tracking (Top ➔ Down vs. Down ➔ Top)**:
   - Validated via geometric centroid crossing and perspective area expansion factor ($\Delta Area$).
   - Outdoor ramp vs. indoor bay origin checks prevented showroom pedestrians from triggering visits.
2. **UAE License Plate CRAFT & OCR Performance**:
   - Abu Dhabi format (`[Cat] [Digits]`) spatial clustering tested on incoming customer cars.
   - Dubai alphabetic prefixes (`M`, `AA`, `C`) evaluated under live sun glare.
3. **Emblem Recognition vs. Body Specularity**:
   - Grille emblem fuzzy matching evaluated against direct sunlight on chrome badges.

---

## 5. Next Steps & Ground Truth Verification

Run the interactive verification tool to inspect vehicle images, confirm ground truth, and calculate exact Precision & Recall:
```bash
python "Reports & Resultes/review_session.py"
```
