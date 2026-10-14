# Task List - Vehicle Visits Tracker

## Phase 1: Local Backend & Database Setup
- [x] Initialize project directory structure (backend/, frontend/, edge/)
- [x] Setup local MySQL database & execute table migrations
- [x] Build FastAPI server base configuration with CORS & DB connection pool
- [x] Implement JWT user authentication (Admin login)
- [x] Integrate YOLOv8 object detector for vehicle detection
- [x] Integrate EasyOCR for reading license plate text
- [x] Integrate vehicle color and brand classifier
- [x] Implement camera snapshot endpoint (`/api/capture`) with full AI pipeline
- [x] Set up FastAPI WebSocket endpoint to broadcast events in real-time

## Phase 2: RPi Edge & Simulation Setup
- [x] Create `test_sender.py` script on Windows laptop to simulate RPi snapshot uploads
- [x] Create `edge_tracker.py` client script for Raspberry Pi with OpenCV motion detection
- [x] Implement dual sensor-based direction detection logic (Entry vs Exit) in the RPi script
- [x] Implement offline caching in the RPi script to queue images if network is disconnected

## Phase 3: React Frontend Dashboard
- [x] Create React/Vite project in frontend/ with TypeScript & custom CSS variables
- [x] Build dashboard layout (Glassmorphism, dark/light theme, modern cards)
- [x] Add main statistics display (vehicles inside, daily entry/exit counts)
- [x] Build real-time event feed powered by WebSockets
- [x] Create interface to search and manage vehicle/owner details
- [x] Add manual entry & edit modals for visits (including manual override logic)

## Phase 4: Integration, Testing & Migration
- [x] Run full end-to-end simulation on Windows laptop using `test_sender.py`
- [x] Perform network integration testing with a real Raspberry Pi
- [x] Document cloud migration and production deployment steps
