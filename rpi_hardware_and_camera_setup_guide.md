# 📸 Raspberry Pi Hardware & Camera Setup Guide

Setting up the physical edge hardware (Raspberry Pi & Cameras) is key to moving from simulation to real-world tracking. Follow this step-by-step guide to assemble, configure, calibrate, and launch your Raspberry Pi edge client.

---

## 🛠️ Step 1: Hardware Assembly & Camera Placement

### 1. Connecting the Camera to the Raspberry Pi
- **USB Webcam (Recommended):** Simply plug the USB webcam into one of the blue USB 3.0 ports on your Raspberry Pi 4 or 5.
- **Pi Camera Module (v3 / Wide):** Power down the Pi. Gently lift the plastic collar on the camera port (labelled `CAMERA` or `CAM/DISP`), insert the ribbon cable with the silver contacts facing the HDMI ports, and push the collar down to lock it.

### 2. Camera Positioning Tips
- **Mount Height:** Position the camera at about **1.0 to 1.5 meters** above the ground.
- **Angle:** Tilt the camera slightly downward (around 15° to 30°). Avoid mounting it directly facing headlights or sunlight to prevent glare and overexposure.
- **Frame Composition:** The camera should face the gate so that vehicles pass through the middle of the frame from top-to-bottom (or bottom-to-top). The license plate must occupy at least 15–20% of the horizontal frame width when it crosses the tripwires for the AI to read it.

---

## 💾 Step 2: Raspberry Pi OS Installation & Boot Setup

To run the camera tracker headlessly (without needing a monitor, keyboard, or mouse plugged into the Pi):

1. **Download Raspberry Pi Imager** on your Windows laptop.
2. Insert your MicroSD card into your laptop.
3. In Raspberry Pi Imager:
   - **Choose OS:** Select **Raspberry Pi OS (64-bit) Lite** (highly optimized for headless operation).
   - **Choose Storage:** Select your MicroSD card.
4. Click **Next** and choose to **Edit Settings** (Configuration Options):
   - **Set username and password:** (e.g., `admin` / `securepassword`).
   - **Configure Wireless LAN:** Enter your Wi-Fi Name (SSID) and Password (must be the **same Wi-Fi network** your Windows laptop is on).
   - **Services tab:** Check **Enable SSH** (use password authentication).
5. Write and flash the card. Once completed, insert it into the Pi and power it on.

---

## 💻 Step 3: Connect and Configure Software on the Pi

### 1. SSH into the Pi
On your Windows laptop, open PowerShell and connect to the Pi:
```bash
ssh admin@<IP_ADDRESS_OF_RPI>
# Or use the local hostname:
ssh admin@raspberrypi.local
```
*(Enter the password you configured in Step 2).*

### 2. Update and Install Packages
Run these commands on the Pi terminal to install Python and system dependencies for OpenCV:
```bash
sudo apt update && sudo apt upgrade -y

# Install git, python3-pip, and python3-venv
sudo apt install -y python3-pip python3-venv git

# Install libraries required to run OpenCV headlessly
sudo apt install -y libgl1-mesa-glx libglib2.0-0
```

### 3. Copy/Clone the Client Code
1. Create a directory for the client tracker:
   ```bash
   mkdir -p ~/visits_tracker/edge
   cd ~/visits_tracker/edge
   ```
2. Copy the contents of the edge tracker file from your host machine into `edge_tracker.py` on the Pi (you can use `nano edge_tracker.py` and paste the contents).

### 4. Create virtual environment & Install Python libraries
```bash
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install numpy opencv-python-headless requests
```

---

## 📏 Step 4: Calibrate your Virtual Tripwires

The OpenCV script uses two virtual tripwires drawn as horizontal lines across the camera frame to detect direction.

```text
+------------------------------+  <- Top of camera frame
|                              |
|   - - - - - - - - - - - -    |  <- Tripwire 1 (TRIPWIRE_1_Y = 0.3)
|       (Outside Gate)         |
|                              |
|                              |
|   - - - - - - - - - - - -    |  <- Tripwire 2 (TRIPWIRE_2_Y = 0.7)
|       (Inside Workshop)      |
|                              |
+------------------------------+  <- Bottom of camera frame
```

### How to Adjust:
1. Open the script in a terminal editor:
   ```bash
   nano edge_tracker.py
   ```
2. Modify the configuration parameters:
   - **`API_URL`:** Point it to your Windows laptop's local IP address (e.g., `http://192.168.1.15:8000/api/capture`).
   - **`ZONE`:** Set to `"Zone A"` for Ground Floor, or `"Zone B"` for the Basement Pi.
   - **`TRIPWIRE_1_Y` & `TRIPWIRE_2_Y`:** These represent the position of the lines as percentages of the frame height (0.0 = top, 1.0 = bottom).
     - If a car approaching from the street crosses **Tripwire 1 first, then Tripwire 2** $\rightarrow$ **`Entry`** is triggered.
     - If a car exiting the workshop crosses **Tripwire 2 first, then Tripwire 1** $\rightarrow$ **`Exit`** is triggered.
3. Save and close (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

## ⚙️ Step 5: Make it Run Automatically on Boot (Systemd)

To make the script start tracking automatically when the Raspberry Pi turns on:

1. Create a systemd daemon service file on the Pi:
   ```bash
   sudo nano /etc/systemd/system/gate-tracker.service
   ```
2. Paste the following configuration:
   ```ini
   [Unit]
   Description=Workshop Gate Camera Tracker Service
   After=network.target

   [Service]
   User=admin
   WorkingDirectory=/home/admin/visits_tracker/edge
   ExecStart=/home/admin/visits_tracker/edge/venv/bin/python edge_tracker.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   *(Ensure the `User` and `WorkingDirectory` paths match your Pi's username).*
3. Save and close. Then enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable gate-tracker.service --now
   ```
4. To check the real-time logs of the camera triggers:
   ```bash
   sudo journalctl -u gate-tracker.service -f
   ```

---

## 🧪 Step 6: Verify the Setup

1. Make sure your Windows laptop backend is running:
   ```bash
   venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
2. Open the dashboard at `http://localhost:5173/` on your browser.
3. Have a vehicle drive through the gate.
4. **Watch the live logs on your Pi:** You should see `Tripwire triggered` and `Motion direction recognized: Entry. Snapshot saved to local cache.`
5. **Watch the dashboard on your laptop:** A shimmering scanning card will pop up immediately, and after a couple of seconds, it will update with the detected plate, color, and brand!

---

## 🚀 Live Active Deployment Reference

| Component | Target / Host | Address / Port | Status |
| :--- | :--- | :--- | :--- |
| **Raspberry Pi 4/5** | `VenenoMainRP` | `192.168.0.240` (SSH User: `admin`) | **ONLINE & RUNNING** |
| **Camera Hardware** | Logitech Brio 100 | `/dev/video0` (V4L2 MJPEG 1280x720 @ 30 FPS) | **CONNECTED** |
| **Edge Tracker Daemon** | systemd service | `gate-tracker.service` (auto-starts on boot) | **ACTIVE (RUNNING)** |
| **Live Camera Preview** | Web Streamer | `http://192.168.0.240:8080/` | **LIVE (HTTP 200)** |
| **Laptop AI Backend** | FastAPI / YOLOv8 | `http://192.168.0.24:8000/api/capture` | **LISTENING** |
| **React Dashboard** | Vite Dashboard | `http://localhost:5173/` | **READY** |

### Useful Commands on the Raspberry Pi:
```bash
# Check service status
systemctl status gate-tracker.service

# Follow live camera detection logs in real time
journalctl -u gate-tracker.service -f

# Restart tracker service (e.g. after adjusting tripwires)
sudo systemctl restart gate-tracker.service
```

