# AI Continual Learning & Full-Stack Upgrade Plan

## Goal Description

Transform **Vehicle Visits Tracker (`CallMyCar`)** from a static, rule-bound detection script into a **Self-Improving, Continual Learning AI System** engineered for your existing hardware:
* **Backend Host:** 13th Gen Intel Core i7-13650HX (14 cores / 20 threads), 24 GB RAM, **NVIDIA GeForce RTX 5050 Laptop GPU (8 GB VRAM)** (with automatic CPU fallback for cloud portability).
* **Edge Controller:** Raspberry Pi 4/5 (`VenenoMainRP`) + Logitech Brio 100 (1280×720 @ 30 FPS).

### What This Upgrade Accomplishes
1. **Hardware Acceleration (`CUDA` + Auto-Fallback):** Unlocks GPU acceleration in PyTorch, YOLOv8, EasyOCR, and neural feature extraction (`cuda:0` when available, graceful CPU fallback), cutting inference latency from seconds to ~60–120 ms while freeing headroom for multi-pass analysis and local model fine-tuning.
2. **Loop 1 — Instant Online Continual Learning (Zero-Latency Memory):**
   * **512-D Neural Visual Embeddings (`MobileNetV3-Large` / `ResNet` feature extractor):** Every scanned or corrected vehicle is encoded into an L2-normalized appearance vector stored in the database.
   * **Learned Brand & Color Prototype Classifier (k-NN + Neural Head):** Replaces the brittle grille-text-only brand logic and static HSV color thresholds with a hybrid classifier combining visual prototype similarity (k-NN over verified workshop vehicles), fine-tuned neural classification heads, and OCR/HSV priors.
   * **Learned OCR Alias & Confusion Memory:** When a human corrects a misread plate (e.g., `5S456` $\rightarrow$ `10 55456` or `1055456` $\rightarrow$ `10 55456`), the system records an explicit `PlateAlias` mapping and updates character confusion weights so the same customer car is recognized automatically on its very next visit.
   * **Visual Re-Identification (Re-ID) for Unreadable Plates & Reverse Exits:** Automatically ranks candidate vehicles on `UNVERIFIED_EXIT` and matches `UNREADABLE-*` entries against known customer vehicles using cosine similarity of visual embeddings + color/brand match.
3. **Loop 2 — Local GPU Fine-Tuning & Gold Dataset Curation:**
   * **Smart Tiered Storage Policy:** Routine raw snapshots in `backend/uploads/` still auto-clean after 48 hours, while human-verified / corrected vehicle crops, license plate crops, and hard negatives (false triggers) are archived as compact JPEG crops (`~30–60 KB`) in `backend/learning_data/` with a configurable diversity cap (max 5 samples per plate, 2 GB cap).
   * **On-Demand & Scheduled Local Fine-Tuning:** Trains/fine-tunes a lightweight PyTorch Brand & Color Multi-Head Classifier (and exports YOLO plate/vehicle annotations) directly on your RTX 5050 GPU in seconds—either via a 1-click button in the dashboard or automatically after $N$ new corrections.
4. **Edge Sharpness-Aware Frame Scoring & Dynamic Config Sync:**
   * Upgrades [edge_tracker.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/edge/edge_tracker.py) on the Raspberry Pi to score candidate frames using **Laplacian sharpness variance + optimal lower-third plate positioning + contour area** instead of raw contour area alone, eliminating motion-blurred captures while keeping 30 FPS on the Pi CPU.
5. **Plate Formatting Bug Fix & Unified Normalization:**
   * Fixes the mismatch between [ai_pipeline.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/ai_pipeline.py) (which preserves UAE category/code spaces like `"10 55456"`) and [main.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/main.py#L799) (which previously stripped spaces on manual edits into `"1055456"`), ensuring 100% consistent plate keys across AI scans and manual edits.

---

## System Architecture & Continual Learning Pipeline

```mermaid
flowchart TD
    subgraph Edge["Raspberry Pi 4/5 (Edge @ 30 FPS)"]
        Cam["Logitech Brio 100 (720p)"] --> MOG["MOG2 + Driveway Corridor Mask"]
        MOG --> Sharp["Sharpness-Aware Best-Frame Scorer (Laplacian + Area + Position)"]
        Sharp -->|HTTP POST /api/capture| API["FastAPI Backend Server"]
    end

    subgraph Inference["Loop 1: GPU-Accelerated Inference & Online Memory (RTX 5050 / CPU Fallback)"]
        API --> YOLO["YOLOv8 Vehicle & Plate ROI Detector (CUDA)"]
        YOLO --> Embed["512-D Visual Embedding Extractor (MobileNetV3-Large)"]
        YOLO --> OCR["Multi-Pass EasyOCR (CUDA) + UAE Format Parser"]
        OCR --> Alias["Learned Plate Alias & Confusion Corrector"]
        Embed --> KNN["Visual Memory Bank (k-NN Re-ID + Brand/Color Prototypes)"]
        Embed --> Head["Fine-Tuned Brand & Color Neural Heads"]
        Alias & KNN & Head --> Fusion["Confidence-Weighted Decision Fusion"]
    end

    subgraph HITL["Human-in-the-Loop & Gold Dataset Curation"]
        Fusion -->|WebSocket Broadcast| UI["React Dashboard + AI Brain Tab"]
        UI -->|Edit Visit / Confirm Exit / Mark False Scan| Feedback["Feedback & Correction Engine"]
        Feedback -->|Instant <10ms Update| KNN
        Feedback -->|Instant <10ms Update| Alias
        Feedback -->|Archive Compact Crops| Gold["Protected Gold Dataset (backend/learning_data/)"]
    end

    subgraph Training["Loop 2: Local GPU Fine-Tuning Engine"]
        Gold -->|1-Click or Auto-Trigger (>=20 new samples)| Trainer["PyTorch GPU Fine-Tuner (Brand/Color Heads + YOLO Dataset Export)"]
        Trainer -->|Hot-Swap Weights Without Downtime| Head
    end
```

---

## User Review Required

> [!IMPORTANT]
> **PyTorch CUDA Wheel Check in Virtual Environment**
> Your system has an **NVIDIA GeForce RTX 5050 Laptop GPU (8 GB VRAM, CUDA 13.3 driver)**. If the existing `venv` currently has the CPU-only build of `torch` installed, we will upgrade `torch` and `torchvision` to the CUDA-enabled wheel (`cu124`/`cu126`) so both inference and fine-tuning run on the RTX 5050 GPU, while maintaining automatic fallback to CPU if `torch.cuda.is_available()` is `False`.

> [!NOTE]
> **Non-Destructive Database Schema Migration**
> All new columns on `visits` and `vehicles` and the new continual learning tables (`ai_feedback_logs`, `plate_aliases`, `vehicle_embeddings`, `ai_training_runs`) will be applied automatically on startup via safe `ALTER TABLE ... ADD COLUMN` / `CREATE TABLE IF NOT EXISTS` migrations in [database.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/database.py) so existing SQLite and MySQL data is 100% preserved.

---

## Proposed Changes

### Component 1: Database Schema & Continual Learning Models

#### [MODIFY] [database.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/database.py)
* Add safe automatic schema migration (`run_auto_migrations(engine)`) so existing `visits` and `vehicles` tables gain new AI telemetry columns without dropping existing data.
* Extend `Visit` with:
  * `predicted_plate` (`String(20)`), `predicted_color` (`String(30)`), `predicted_brand` (`String(50)`) — preserves the original AI prediction before human edits so accuracy can be measured and learned from.
  * `ai_confidence` (`Float`, default `0.0`) — overall confidence score (`0.0` to `1.0`).
  * `match_source` (`String(40)`, default `"yolo_ocr"`) — e.g., `"yolo_ocr"`, `"learned_alias"`, `"visual_reid"`, `"manual"`.
  * `vehicle_bbox` (`String(60)`, JSON `[x1, y1, x2, y2]`) — stored so when a user edits a record later, the exact vehicle and plate crops can be extracted and archived into the Gold Dataset.
* Add 4 new tables for Continual Learning:
  1. `PlateAlias`: Maps frequent OCR misreads (`raw_ocr_plate`) $\rightarrow$ verified `canonical_plate` with `hit_count`, `confidence`, and `last_seen`.
  2. `VehicleEmbedding`: Stores 512-D L2-normalized visual appearance vectors (`embedding_json`), verified `plate_number`, `brand`, `color`, `direction` (`Entry`/`Exit`), `crop_path`, and `is_gold_verified` flag.
  3. `AIFeedbackLog`: Audit log of every human correction or verification (`visit_id`, `original_plate`, `corrected_plate`, `original_brand`, `corrected_brand`, `original_color`, `corrected_color`, `feedback_type` in `['edit', 'confirm_exit', 'verify_correct', 'false_positive']`, `archived_crop_path`, `used_in_training`).
  4. `AITrainingRun`: Tracks local GPU/CPU fine-tuning jobs (`id`, `started_at`, `completed_at`, `device_used`, `samples_count`, `epochs`, `val_brand_acc`, `val_color_acc`, `status`, `model_version`).

#### [MODIFY] [schema.sql](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/schema.sql)
* Synchronize `schema.sql` with the new columns and continual learning tables for clean cloud MySQL deployments.

---

### Component 2:Continual Learning Engine & Local GPU Trainer

#### [NEW] [learning_engine.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/learning_engine.py)
Creates the core **Continual Learning & Memory Engine** with both **Loop 1 (Online Memory)** and **Loop 2 (Local GPU Fine-Tuning)**:
* **Hardware Manager (`get_compute_device()`):** Detects `cuda:0` (`NVIDIA GeForce RTX 5050 Laptop GPU`), enables cuDNN benchmark and TF32/FP16 optimizations, and falls back cleanly to CPU.
* **Canonical Plate Normalizer (`normalize_plate_key(raw_str)`):**
  * Fixes the space-stripping bug by normalizing both AI outputs and manual human edits to a single canonical UAE format (e.g. `"10 55456"`, `"M 11770"`, or `"55456"`), while also indexing space-stripped keys (`"1055456"`) for instant cross-lookup.
* **512-D Visual Feature Extractor (`extract_vehicle_embedding(crop_bgr)`):**
  * Uses pretrained `torchvision.models.mobilenet_v3_large(weights=DEFAULT)` (running on GPU in `<8ms`) to extract a 960-D / 512-D L2-normalized feature vector from the vehicle crop (plus a color histogram + spatial HSV descriptor concatenated for lighting-invariant color awareness).
* **Online Memory Lookup (`predict_from_memory(embedding, raw_ocr_candidates, direction)`):**
  * **OCR Alias Resolution:** Checks if any OCR candidate (or high-similarity Levenshtein match $\ge 0.82$) exists in `PlateAlias` or active/known `Vehicle` records.
  * **Visual k-NN Prototype Classifier:** Computes cosine similarity against verified `VehicleEmbedding` vectors in the memory bank:
    * Predicts `brand` and `color` using distance-weighted k-NN voting combined with the fine-tuned neural head (`brand_color_head.pt` if trained).
    * Computes **Visual Re-ID Match Scores** (`0–100%`) against vehicles currently `Inside` (for `UNVERIFIED_EXIT` ranking) and returning customer vehicles (for `UNREADABLE` entry suggestions).
* **Gold Dataset Archiver (`record_human_feedback(...)`):**
  * Triggered automatically whenever an operator edits a visit, updates vehicle brand/color, confirms an unverified exit, verifies a scan, or marks a false positive.
  * Crops the vehicle (and plate ROI) from the snapshot, saves compact JPEGs to `backend/learning_data/gold_vehicles/` or `backend/learning_data/hard_negatives/` + YOLO-format `.txt` annotations (`backend/learning_data/yolo_dataset/`), enforces the diversity cap (max 5 crops per plate, 2 GB disk cap), updates `PlateAlias` + `VehicleEmbedding` immediately in RAM and DB, and triggers background GPU fine-tuning if `untrained_feedback_count >= 20`.
* **Local GPU Fine-Tuner (`run_local_finetuning(db, progress_callback)`):**
  * Trains a lightweight multi-task PyTorch MLP/Linear Probe head (`BrandColorAdapterHead`) on top of cached/augmented visual embeddings + color descriptors for 25 epochs on the RTX 5050 GPU (completes in `<5 seconds` for hundreds of samples), validates accuracy, hot-swaps the active weights in memory without restarting FastAPI, and logs the run to `AITrainingRun`.

---

### Component 3: Upgraded AI Inference Pipeline

#### [MODIFY] [ai_pipeline.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/ai_pipeline.py)
* **Enable GPU Acceleration:**
  * Initialize `easyocr.Reader(['en'], gpu=torch.cuda.is_available())`.
  * Move `yolo_model` (`yolov8n.pt` or custom fine-tuned `learning_data/models/best_yolo.pt` if present) onto `cuda:0` when available.
* **Dedicated Plate ROI Localization + Multi-Pass OCR:**
  * Before running full-bumper OCR, detect rectangular high-contrast plate contours / aspect-ratio ROIs inside the lower vehicle crop so EasyOCR reads a tight, upscaled plate crop in addition to the multi-pass bumper scan.
  * Pass raw OCR candidates through `learning_engine.resolve_plate_with_aliases()` so learned human corrections immediately fix recurring OCR character confusions.
* **Hybrid Neural + Memory + HSV/OCR Brand & Color Classification:**
  * Upgrade [`classify_brand`](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/ai_pipeline.py#L352-L401) to fuse:
    1. Fine-tuned Neural Head + Visual k-NN Memory similarity (works on graphic logos like Mercedes, BMW, Toyota, Audi, Porsche, Nissan, Lexus even when zero text is readable!), and
    2. Grille/Emblem OCR fuzzy matching (`KNOWN_BRANDS`).
  * Upgrade [`classify_color`](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/ai_pipeline.py#L275-L350) to fuse:
    1. Fine-tuned Color Head + Visual Memory Under Workshop Lighting, and
    2. Illumination-normalized LAB + HSV body-panel segmentation.
* **Return Rich AI Telemetry:**
  * `run_ai_pipeline()` now returns `embedding`, `ai_confidence`, `match_source`, `reid_candidates` (top visually matching known plates), and `coords` (`[x1, y1, x2, y2]`).

---

### Component 4: FastAPI Endpoints, Lifecycle & Smart Storage

#### [MODIFY] [main.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/main.py)
* **Fix Plate Normalization Across All Endpoints:**
  * Replace `re.sub(r'[^A-Z0-9]', '', plate_number.upper())` in `PUT /api/vehicles/{plate_number}`, `POST /api/visits/manual`, and `PUT /api/visits/{visit_id}` with `normalize_plate_key(plate_number)` so `"10 55456"` and `"1055456"` resolve to the same canonical format (`"10 55456"`).
* **Capture Background Pipeline (`process_capture_background`):**
  * Persist `predicted_plate`, `predicted_color`, `predicted_brand`, `ai_confidence`, `match_source`, and `vehicle_bbox` on every `Visit`.
  * Store the vehicle's `512-D` visual embedding for active `Inside` visits.
  * **Smart `UNVERIFIED_EXIT` Ranking & Auto-Match:** When a vehicle exits in reverse or with an obscured plate, compute the cosine similarity between the exiting vehicle's visual embedding + color/brand and every currently `Inside` vehicle! Attach `similarity_score` (`0–100%`) to each candidate and sort candidates highest-match-first in the WebSocket payload.
  * **Smart `UNREADABLE` Entry Re-ID Suggestion:** When a vehicle enters with an obscured plate (`UNREADABLE-*`), check the visual memory bank for returning customer cars with $\ge 88\%$ visual + brand + color similarity and include `suggested_plate` in the visit payload.
* **Implicit Continual Learning Hooks on Existing Endpoints:**
  * `PUT /api/visits/{visit_id}` (`edit_visit_record`): Automatically compares the edited `plate_number`, `brand`, and `color` against `visit.predicted_plate`, `visit.predicted_brand`, `visit.predicted_color`, calls `record_human_feedback()`, updates `PlateAlias` + `VehicleEmbedding`, and archives the Gold Crop.
  * `PUT /api/vehicles/{plate_number}` (`update_vehicle_owner_info`): Updates `VehicleEmbedding` prototypes for that plate's brand and color.
  * `POST /api/visits/confirm-unverified-exit`: Logs the confirmed exit pair (`entry_image_url` $\leftrightarrow$ `exit_image_url`) into the Visual Re-ID memory bank so the system learns front-to-rear/reverse appearance matching for that vehicle.
* **New Continual Learning & Feedback API Endpoints:**
  * `POST /api/visits/{visit_id}/verify` — 1-click confirmation that an AI scan is 100% accurate (promotes crop to Gold Dataset).
  * `POST /api/visits/{visit_id}/false-positive` — Marks a scan as a false trigger (e.g. shadow, glare, parked car), archives the crop to `learning_data/hard_negatives/`, and removes the false visit from the active feed.
  * `GET /api/ai/stats` — Returns hardware status (`device_name`, `cuda_available`, `vram_mb`), rolling accuracy metrics (Plate Accuracy %, Brand Accuracy %, Color Accuracy % calculated from `visits` vs `manually_edited` logs), memory bank counts (Total Embeddings, Gold Crops, Hard Negatives, Learned Plate Aliases), recent `AIFeedbackLog` items, and `AITrainingRun` history.
  * `POST /api/ai/train` — Triggers an immediate background fine-tuning job on the RTX 5050 GPU (or CPU) and broadcasts live progress (`AI_TRAINING_PROGRESS` / `AI_TRAINING_COMPLETE`) over WebSockets.
  * `GET /api/edge/config` — Serves calibrated corridor/tripwire/sharpness parameters to the Raspberry Pi for dynamic edge config sync.

#### [MODIFY] [maintenance.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/backend/maintenance.py)
* Keep the 48-hour cleanup strictly scoped to raw full-frame uploads in `backend/uploads/`.
* Before deleting an expired raw image in `backend/uploads/`, check if it belongs to a `manually_edited` visit that hasn't had its Gold Crop extracted yet—if so, auto-archive the compact crop to `backend/learning_data/` before deleting the raw full frame.
* Report `learning_data` dataset size and sample counts in `get_storage_stats()`.

---

### Component 5: Edge Sharpness-Aware Frame Scoring (Raspberry Pi)

#### [MODIFY] [edge_tracker.py](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/edge/edge_tracker.py)
* **Sharpness-Aware Composite Frame Quality Score (`compute_frame_quality(frame, box)`):**
  * Instead of buffering `best_vehicle_frame` purely when `largest_area_this_frame > max_tracked_area` (which often picks a frame where the car is moving fast and the plate is motion-blurred), compute a fast composite score on the lower-half bumper ROI of the contour (`<1.5ms` on Raspberry Pi CPU):
    $$\text{Quality} = \text{AreaScore} \times (1 + \alpha \cdot \text{LaplacianSharpness}) \times \text{SweetSpotBonus}$$
  * Buffers the **sharpest, best-positioned frame** for upload.
* **Periodic Backend Config Sync:**
  * Every 5 minutes, polls `GET /api/edge/config` (non-blocking in the background uploader thread) to sync any updated tripwire or minimum displacement thresholds from the server.

---

### Component 6: React Dashboard — Implicit Learning Cards & "AI Brain & Learning" Hub

#### [MODIFY] [App.tsx](file:///C:/Users/venen/.gemini/antigravity/worktrees/Car_Visits_Tracker/ai_learning_system_upgrade/frontend/src/App.tsx)
* **Enhanced Activity Feed Cards:**
  * Display AI Confidence & Source badges (e.g., `96% AI`, `🧠 Learned Alias`, `👁️ Visual Memory`).
  * If a scan is `UNREADABLE-*` and the Visual Re-ID engine found a high-confidence match in memory (`suggested_plate`), show a **1-Click "Apply Suggested Plate (`10 55456` - 92% Match)"** pill right on the card!
  * Add a 1-click **"✓ Verify"** button (to confirm a scan into the Gold Dataset) and inside the Edit Visit modal add a **"🗑️ Mark as False Trigger (Teach AI to Ignore)"** button.
* **Upgraded `Unverified Exit` Banner:**
  * Display each candidate vehicle's **Visual Re-ID Similarity Badge** (e.g., `94% Visual Match` highlighted in green for the top candidate) so staff can confirm reverse exits with 1 click.
* **New Navigation Tab: `🧠 AI Brain & Learning`:**
  * **Hardware & Engine Status Card:** Shows `NVIDIA GeForce RTX 5050 (CUDA Active)` or `CPU Mode`, inference speed, and active model version.
  * **Day-to-Day Learning Accuracy Cards:** Rolling Plate OCR Accuracy %, Brand Recognition Accuracy %, Color Recognition Accuracy %, and Total Learned Vehicles.
  * **Knowledge Base Summary:** Counts of Visual Memory Embeddings, Learned Plate Aliases (with a table showing `Raw OCR Misread -> Learned Plate`), Gold Dataset Crops, and Hard Negatives.
  * **1-Click GPU Fine-Tuning Control:** `"Fine-Tune AI Model Now"` button with real-time progress bar via WebSocket, plus a table of recent training runs and recent human corrections that the AI learned from.

---

## Verification Plan

### Automated Tests
1. **CUDA & Environment Verification:**
   ```powershell
   & "D:\Veneno\CallMyCar\Car_Visits_Tracker\backend\venv\Scripts\python.exe" -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
   ```
2. **Continual Learning & Pipeline Automated Test Suite (`backend/test_learning_system.py`):**
   We will create and run an end-to-end automated verification script that tests:
   * Canonical UAE plate normalization (`"10 55456"` vs `"1055456"`, `"M 11770"` vs `"M11770"`).
   * 512-D visual embedding extraction and cosine similarity Re-ID matching.
   * Instant Online Learning: simulating an OCR misread (`"10 5S456"`), applying a human edit to `"10 55456"` with brand `"Porsche"` and color `"White"`, and verifying that the next scan of that vehicle immediately resolves the plate via `PlateAlias` and predicts `"Porsche"` / `"White"` via visual memory.
   * Gold Dataset crop archiving in `backend/learning_data/` and verifying that `cleanup_old_images()` in `maintenance.py` preserves `learning_data/` crops.
   * Running a full local GPU fine-tuning cycle (`run_local_finetuning()`) on the RTX 5050 and verifying model weight hot-swapping and accuracy improvement.
   ```powershell
   & "D:\Veneno\CallMyCar\Car_Visits_Tracker\backend\venv\Scripts\python.exe" backend\test_learning_system.py
   ```
3. **Frontend TypeScript & Production Build Check:**
   ```powershell
   npm --prefix frontend run build
   ```

### Manual Verification
1. Start the FastAPI backend (`uvicorn main:app --host 0.0.0.0 --port 8000`) and React frontend (`npm run dev`).
2. Open the dashboard at `http://localhost:5173/` and navigate to the new **🧠 AI Brain & Learning** tab to verify GPU status (`NVIDIA GeForce RTX 5050`), accuracy metrics, and memory bank stats.
3. Edit any visit record's plate, brand, or color (or click **✓ Verify** on an event card), then check the **AI Brain & Learning** tab to see the correction logged in real time and the Gold Crop count increment.
4. Click **"Fine-Tune AI Model Now"** in the dashboard and observe the live training completion toast and updated model version.
