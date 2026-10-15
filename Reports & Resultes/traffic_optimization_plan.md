# Traffic Optimization & Machine Learning Action Plan

**Date**: October 15, 2026  
**Purpose**: Post-Traffic Optimization Strategy Based on Real-World Session Data  

---

## 1. Objective
Iterate on the live computer vision pipeline based on real vehicle arrivals, sun reflections, approach angles, and speeds recorded between 10:00 AM and 12:00 PM.

---

## 2. Optimization Branches

### Branch A: Edge Tracking Calibration
- **Speed & Cooldown**: Assess if fast-moving cars or tailgating vehicles require reducing `CAPTURE_COOLDOWN` from 12s to 6-8s with track ID debouncing.
- **Sun Glare & Dynamic Lighting**: If bright morning sunlight between 10 AM - 12 PM washes out the camera sensor, enable automatic exposure lock or dynamic CLAHE (Contrast Limited Adaptive Histogram Equalization).

### Branch B: UAE ALPR Recognition Upgrades
- **Abu Dhabi Category Preservation**: Review any unreadable visits to see if vertical emblems or colored boxes failed OCR segmentation.
- **Dubai / Northern Emirates Formats**: Verify Sharjah, Ajman, and Ras Al Khaimah plate patterns observed in the dataset.

### Branch C: Fleet Database Expansion
- For vehicles that enter regularly (staff, VIP clients, regular service appointments), ensure manual edits in the dashboard permanently link Make, Model, and Owner details to the plate for zero-error instant check-in.

---

## 3. Timeline & Deliverables
1. **12:00 PM - 12:30 PM**: Run Ground Truth Review (`review_session.py`).
2. **12:30 PM - 01:00 PM**: Apply hyperparameter adjustments to `ai_pipeline.py` and `edge_tracker.py`.
3. **01:00 PM**: Push final weights and settings to GitHub main and deploy to Raspberry Pi.
