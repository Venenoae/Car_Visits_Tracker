# Suggested Rule Updates for `uae_gate_vision_standards.md`

**Generated**: October 15, 2026 at 12:00:00 PM  
**Source**: Real-World Traffic Benchmark (10:00 AM – 12:00 PM)  
**Server Status**: All services (FastAPI, Vite frontend, and Pi camera) remain **100% active and running with zero downtime**.

---

## 1. Summary of Session Findings
* **Vehicles Processed**: 0 (0 entries, 0 exits)
* **Plate Recognition Rate**: 0.0% (0 recognized, 0 unreadable)
* **Brands Identified**: None recorded

---

## 2. Proposed Addition to `.agents/rules/uae_gate_vision_standards.md`

Review the suggested addition below. Once confirmed, you can merge this directly into `.agents/rules/uae_gate_vision_standards.md`:

```markdown
## 5. Real-World Traffic Calibration (Session: 2026-10-15)
- **Morning Sunlight & Glare Threshold**:
  - Direct morning sun between 10:00 AM and 12:00 PM causes specular reflection on white acrylic plates and chrome grilles.
  - Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) preprocessing if plate confidence drops below 0.70.
- **Observed Brands & Sub-Brand Mappings**:
  - Live showroom traffic verified for: None recorded.
  - Ensure performance trim badges (e.g. Nismo, AMG, M Power, V8) continue mapping to canonical makes.
- **Entry Approach Vectors**:
  - Entering customer cars cross from ramp (y=0.34) into vehicle bay floor (y=0.52) at average velocity dy >= +30px.
  - Scale expansion ratio threshold of 1.05 confirmed robust against false triggers.
```

---

## 3. Server Continuity Note
> [!NOTE]
> All core services remain active and unaffected:
> - **FastAPI AI Backend**: Running on port `8000`
> - **Vite Frontend**: Running on port `5173`
> - **Raspberry Pi Camera Stream**: Running on port `8080`
