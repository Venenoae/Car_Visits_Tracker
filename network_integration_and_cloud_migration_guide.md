# 🌐 Network Integration & Cloud Migration Guide

This guide provides step-by-step instructions to connect your physical Raspberry Pi camera clients to your local Windows laptop for integration testing, followed by the complete procedure to migrate the entire system to a secure cloud server.

---

## 🔌 Part 1: Local Network Integration Testing (RPi to Laptop)

By default, the uvicorn server runs on `127.0.0.1:8000` (localhost), which only accepts traffic from your laptop itself. To test with a real Raspberry Pi on your local network (LAN), follow these steps:

### 1. Configure the Windows Laptop Backend
We have configured your backend to run on `0.0.0.0`, which means it listens for traffic on all local network adapters:
```bash
venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Find Your Windows Laptop IP Address
1. Open PowerShell or Command Prompt on your Windows laptop.
2. Run the following command:
   ```cmd
   ipconfig
   ```
3. Locate your active network adapter (usually "Wireless LAN adapter Wi-Fi" or "Ethernet adapter").
4. Note the **IPv4 Address** (e.g., `192.168.1.15`).

### 3. Open Windows Firewall Port (8000)
Windows Firewall blocks incoming traffic on port 8000 by default. You need to allow it:
1. Open the Start menu, type **Windows Defender Firewall with Advanced Security**, and press Enter.
2. In the left panel, click **Inbound Rules**.
3. In the right panel, click **New Rule...**
4. Select **Port** and click Next.
5. Choose **TCP** and specify port **8000** under **Specific local ports**, then click Next.
6. Select **Allow the connection** and click Next.
7. Keep all checkboxes marked (Domain, Private, Public) and click Next.
8. Name the rule (e.g., `CallMyCar API Port 8000`) and click **Finish**.

### 4. Connect and Test from the Raspberry Pi
1. Power up your Raspberry Pi and ensure it is connected to the **same Wi-Fi network** as your Windows laptop.
2. Open a terminal on the Raspberry Pi and test the connection using `curl` or `ping`:
   ```bash
   ping <YOUR_LAPTOP_IP>
   # Example: ping 192.168.1.15
   
   curl http://<YOUR_LAPTOP_IP>:8000/api/dashboard/stats
   # Example: curl http://192.168.1.15:8000/api/dashboard/stats
   ```
   *If successful, the curl command should return the JSON object representing today's stats.*

### 5. Configure the Edge Tracker Script
1. On the Raspberry Pi, edit [edge_tracker.py](file:///d:/Veneno/CallMyCar/Car_Visits_Tracker/edge/edge_tracker.py):
   ```python
   # Line 10: Change the API URL to point to your laptop's IP
   API_URL = "http://<YOUR_LAPTOP_IP>:8000/api/capture"
   ```
2. Run the tracker script:
   ```bash
   python3 edge_tracker.py
   ```
3. Drive a vehicle past the camera (or simulate motion triggers). The snapshot will upload to your Windows backend, displaying instantly as a scanning loader card before updating on your browser dashboard!

---

## ☁️ Part 2: Cloud Server Production Migration

Once you have verified the edge-to-server communication locally, migrate the system to a production cloud server (such as a VPS on AWS, DigitalOcean, Hetzner, or Linode).

### 1. Provision a VPS (Cloud Server)
- **Recommended OS:** Ubuntu 22.04 LTS (x64).
- **Minimum Specs:** 2 vCPUs, 4 GB RAM, 40 GB SSD (required to run YOLOv8 and EasyOCR pipelines comfortably).

### 2. Export & Migrate the Database (MySQL)
1. Export your local MySQL database schema and records to an SQL dump file:
   ```bash
   mysqldump -u root -p car_visits_tracker > db_dump.sql
   ```
2. Set up a secure MySQL instance on your VPS (or use a managed database instance like AWS RDS).
3. Import the database dump into the cloud database:
   ```bash
   mysql -h <CLOUD_DB_HOST> -u <CLOUD_USER> -p <CLOUD_DB_NAME> < db_dump.sql
   ```

### 3. Server Dependencies Setup
Connect to your VPS via SSH and install required system utilities:
```bash
# Update package lists
sudo apt update && sudo apt upgrade -y

# Install Python, Virtual Env, Nginx, and Git
sudo apt install -y python3-pip python3-venv git nginx

# CRITICAL: Install system libraries required by OpenCV (cv2) on headless servers
sudo apt install -y libgl1-mesa-glx libglib2.0-0
```

### 4. Deploy the Backend Code
1. Clone the project repository onto your VPS:
   ```bash
   git clone <YOUR_REPO_URL> /home/ubuntu/Car_Visits_Tracker
   cd /home/ubuntu/Car_Visits_Tracker/backend
   ```
2. Create and activate a python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install the dependencies:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
4. Create a production environment config file `.env`:
   ```bash
   nano .env
   ```
   Provide your production database credentials and a secure random string for JWT signatures:
   ```ini
   MYSQL_HOST=your-database-host
   MYSQL_PORT=3306
   MYSQL_USER=your-db-user
   MYSQL_PASSWORD=your-secure-password
   MYSQL_DATABASE=car_visits_tracker
   SECRET_KEY=generate-a-secure-64-character-hex-string
   ACCESS_TOKEN_EXPIRE_MINUTES=1440
   UPLOADS_DIR=uploads
   ```

### 5. Setup Uvicorn Daemon Service (Systemd)
To ensure the backend runs continuously in the background and restarts automatically on reboot:
1. Create a systemd unit file:
   ```bash
   sudo nano /etc/systemd/system/callmycar.service
   ```
2. Paste the following configuration:
   ```ini
   [Unit]
   Description=CallMyCar FastAPI Backend Service
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/Car_Visits_Tracker/backend
   ExecStart=/home/ubuntu/Car_Visits_Tracker/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
3. Start and enable the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable callmycar --now
   ```
4. Check the service logs to ensure it starts up completely:
   ```bash
   sudo journalctl -u callmycar -f
   ```

### 6. Configure Nginx Reverse Proxy with WebSockets
1. Open Nginx configuration files:
   ```bash
   sudo nano /etc/nginx/sites-available/callmycar
   ```
2. Configure the server block to handle incoming HTTP requests and WebSocket handshakes:
   ```nginx
   server {
       listen 80;
       server_name api.yourdomain.com; # Replace with your subdomain

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       # Serve uploaded snapshots directly from disk
       location /static/uploads/ {
           alias /home/ubuntu/Car_Visits_Tracker/backend/uploads/;
       }
   }
   ```
3. Enable the configuration and restart Nginx:
   ```bash
   sudo ln -s /etc/nginx/sites-available/callmycar /etc/nginx/sites-enabled/
   sudo systemctl reload nginx
   ```

### 7. Secure the API Server with SSL (HTTPS)
Use Certbot to automatically configure Let's Encrypt certificates for secure HTTP and WebSocket connections:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourdomain.com
```

---

## 🚀 Part 3: Frontend Web Dashboard Production Deployment

1. On your local machine, open `frontend/src/App.tsx`.
2. Locate the API configurations (lines 8–10) and update them to use your secure production domain:
   ```typescript
   const API_BASE = 'https://api.yourdomain.com/api';
   const WS_URL = 'wss://api.yourdomain.com/ws';
   const STATIC_BASE = 'https://api.yourdomain.com';
   ```
3. Compile the production bundle:
   ```bash
   cd frontend
   npm run build
   ```
   *This outputs an optimized, static `dist/` directory.*
4. Deploy the contents of the `dist/` directory to your static hosting provider (e.g. Netlify, Vercel, AWS S3, or via Nginx on your own VPS).

---

## 🛠️ Part 4: Troubleshooting Integration Issues

| Symptom | Probable Cause | Troubleshooting Step |
| :--- | :--- | :--- |
| **RPi fails to ping laptop** | Laptop Wi-Fi profile is set to "Public" (which blocks ICMP). | Open Windows settings, go to Network, select your Wi-Fi, and change the profile from **Public** to **Private**. |
| **Ping works, but curl/POST fails** | Windows Firewall is blocking port 8000. | Ensure you added the Inbound Rule for Port 8000 (TCP) in the Windows Defender Firewall. |
| **OpenCV imports fail on Ubuntu VPS** | Missing graphics rendering system libraries. | Run: `sudo apt install -y libgl1-mesa-glx libglib2.0-0` |
| **WebSockets fail on HTTPS VPS** | Missing proxy upgrade headers in Nginx configuration. | Verify that `proxy_set_header Upgrade $http_upgrade;` and `proxy_set_header Connection "upgrade";` are in your active Nginx site block. |
| **EasyOCR models slow on first run** | Model downloads on the first capture trigger. | Trigger a dummy capture once after deploy. The models will download to `~/.EasyOCR/` and load instantly on subsequent requests. |
